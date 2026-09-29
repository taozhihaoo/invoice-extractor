"""Single-document processing pipeline.

This is the only place where extraction, classification, LLM extraction,
deterministic validation and persistence meet. Every stage records what
actually happened; nothing is claimed to be verified that was not.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ..classification.classifier import DocumentClassifier
from ..database import Database, utc_now
from ..errors import InvalidPdfError, TooManyPagesError
from ..extraction.base import ExtractedDocument
from ..extraction.pipeline import ExtractionPipeline
from ..file_store import FileStore, StoredFile, sha256_hex
from ..llm.base import LLMError
from ..models import (
    Classification,
    DocumentResult,
    DocumentStatus,
    DocumentType,
    ExtractionMethod,
    InvoiceData,
    InvoiceExtraction,
    Usage,
    ValidationResult,
)
from ..upload_validator import SanitisedUpload, validate_upload
from ..validation_rules import build_review_reasons, validate_invoice

if TYPE_CHECKING:
    from ..config import Settings
    from ..llm.base import LLMClient


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def _reasons_or_none(raw: Any) -> list[str]:
    """Row values may be a JSON string or an already-parsed list."""
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def document_result_from_rows(
    document: dict[str, Any],
    extraction: dict[str, Any] | None,
    *,
    duplicate: bool = False,
) -> DocumentResult:
    invoice_extraction = None
    if extraction is not None:
        invoice = InvoiceData(
            supplier=extraction.get("supplier"),
            invoice_number=extraction.get("invoice_number"),
            invoice_date=extraction.get("invoice_date"),
            due_date=extraction.get("due_date"),
            subtotal=_decimal_or_none(extraction.get("subtotal")),
            tax=_decimal_or_none(extraction.get("tax")),
            total=_decimal_or_none(extraction.get("total")),
            currency=extraction.get("currency"),
        )
        invoice_extraction = InvoiceExtraction(
            invoice=invoice,
            validation=ValidationResult(
                passed=(extraction.get("validation_status") == "passed"),
                warnings=_reasons_or_none(extraction.get("validation_warnings")),
            ),
            needs_review=bool(extraction.get("needs_review")),
            review_reasons=_reasons_or_none(extraction.get("review_reasons")),
            llm_provider=extraction.get("llm_provider") or "mock",
            llm_model=extraction.get("llm_model"),
            usage=Usage(
                prompt_tokens=extraction.get("prompt_tokens") or 0,
                completion_tokens=extraction.get("completion_tokens") or 0,
            ),
        )

    document_type = document.get("document_type")
    extraction_method = document.get("extraction_method")

    classification = None
    if document_type:
        classification = Classification(
            document_type=DocumentType(document_type),
            confidence=round(float(document.get("classification_confidence") or 0.0), 2),
            method=document.get("classification_method") or "rules",
        )

    review_reasons: list[str] = []
    if invoice_extraction is not None:
        review_reasons = list(invoice_extraction.review_reasons)
    else:
        review_reasons = _reasons_or_none(document.get("review_reasons"))

    return DocumentResult(
        document_id=document["id"],
        original_filename=document["original_filename"],
        status=DocumentStatus(document["status"]),
        document_type=DocumentType(document_type) if document_type else None,
        page_count=document.get("page_count"),
        extraction_method=ExtractionMethod(extraction_method) if extraction_method else None,
        text_length=document.get("text_length"),
        file_size=document["file_size"],
        sha256=document["sha256"],
        content_type=document.get("content_type"),
        error_message=document.get("error_message"),
        duplicate=duplicate,
        duplicate_of=document["id"] if duplicate else None,
        run_id=document.get("run_id"),
        classification=classification,
        review_reasons=review_reasons,
        created_at=document.get("created_at"),
        updated_at=document.get("updated_at"),
        extraction=invoice_extraction,
    )


class DocumentProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        file_store: FileStore,
        pipeline: ExtractionPipeline,
        classifier: DocumentClassifier,
        llm: LLMClient,
        ocr_available: bool,
    ) -> None:
        self._settings = settings
        self._db = db
        self._file_store = file_store
        self._pipeline = pipeline
        self._classifier = classifier
        self._llm = llm
        self._ocr_available = ocr_available

    def process_upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        run_id: str | None = None,
    ) -> DocumentResult:
        info: SanitisedUpload = validate_upload(
            filename=filename,
            content_type=content_type,
            data=data,
            max_size_bytes=self._settings.max_upload_size_bytes,
        )

        digest = sha256_hex(data)
        existing = self._db.find_document_by_sha256(digest)
        if existing is not None:
            # Same bytes already processed: never re-run extraction/LLM.
            return document_result_from_rows(
                existing,
                self._db.get_extraction(existing["id"]),
                duplicate=True,
            )

        stored = self._file_store.save(data)
        document_id = uuid.uuid4().hex
        now = utc_now()
        self._db.insert_document(
            {
                "id": document_id,
                "original_filename": info.original_filename,
                "content_type": info.content_type,
                "file_size": stored.size,
                "sha256": digest,
                "status": DocumentStatus.PROCESSING.value,
                "storage_path": str(stored.path),
                "run_id": run_id,
                "created_at": now,
                "updated_at": now,
            }
        )

        try:
            return self._process(document_id, stored, info, run_id)
        except (InvalidPdfError, TooManyPagesError) as exc:
            return self._fail(document_id, exc.code, exc.message)
        except LLMError as exc:
            return self._fail(document_id, exc.code, f"LLM extraction failed ({exc.code})")

    # internals ------------------------------------------------------------

    def _process(
        self,
        document_id: str,
        stored: StoredFile,
        info: SanitisedUpload,
        run_id: str | None,
    ) -> DocumentResult:
        extracted: ExtractedDocument = self._pipeline.extract(stored.path)
        classification = self._classifier.classify(extracted.text)

        invoice = None
        validation = None
        usage = Usage()
        llm_model = None
        if classification.document_type is DocumentType.INVOICE:
            result = self._llm.extract_invoice(extracted.text)
            invoice = result.invoice
            usage = result.usage
            llm_model = result.model
            validation = validate_invoice(invoice)

        review_reasons = build_review_reasons(
            document_type=classification.document_type,
            extraction_method=extracted.method,
            ocr_available=self._ocr_available,
            invoice=invoice,
            validation=validation,
        )
        status = (
            DocumentStatus.NEEDS_REVIEW if review_reasons else DocumentStatus.PROCESSED
        )

        now = utc_now()
        self._db.update_document(
            document_id,
            status=status.value,
            document_type=classification.document_type.value,
            classification_method=classification.method,
            classification_confidence=classification.confidence,
            page_count=extracted.page_count,
            extraction_method=extracted.method.value,
            text_length=extracted.text_length,
            review_reasons=json.dumps(review_reasons) if review_reasons else None,
            updated_at=now,
        )

        if invoice is not None:
            self._db.insert_extraction(
                {
                    "document_id": document_id,
                    "supplier": invoice.supplier,
                    "invoice_number": invoice.invoice_number,
                    "invoice_date": invoice.invoice_date,
                    "due_date": invoice.due_date,
                    "subtotal": str(invoice.subtotal) if invoice.subtotal is not None else None,
                    "tax": str(invoice.tax) if invoice.tax is not None else None,
                    "total": str(invoice.total) if invoice.total is not None else None,
                    "currency": invoice.currency,
                    "validation_status": (
                        "passed" if validation is not None and validation.passed else "warning"
                    ),
                    "validation_warnings": (
                        json.dumps(validation.warnings) if validation is not None else None
                    ),
                    "needs_review": int(bool(review_reasons)),
                    "review_reasons": (
                        json.dumps(review_reasons) if review_reasons else None
                    ),
                    "llm_provider": getattr(self._llm, "provider", "mock"),
                    "llm_model": llm_model,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "created_at": now,
                }
            )

        document = self._db.get_document(document_id)
        return document_result_from_rows(
            document, self._db.get_extraction(document_id)
        )

    def _fail(self, document_id: str, code: str, message: str) -> DocumentResult:
        self._db.update_document(
            document_id,
            status=DocumentStatus.FAILED.value,
            error_message=f"{code}: {message}",
            updated_at=utc_now(),
        )
        document = self._db.get_document(document_id)
        return document_result_from_rows(document, None)
