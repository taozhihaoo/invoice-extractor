"""Batch processing: one run, many files, every file independent.

A failure in one file never prevents the others from being processed; each
file ends with its own status (processed / needs_review / failed). Rejected
uploads are recorded as failed documents inside the run so the batch report
shows exactly what arrived and why it was rejected.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import utc_now
from ..errors import BatchTooLargeError, UploadError
from ..file_store import sha256_hex
from ..models import BatchResult, DocumentResult, DocumentStatus
from ..upload_validator import sanitise_filename

if TYPE_CHECKING:
    from ..database import Database
    from .service import DocumentProcessor

logger = logging.getLogger("document_processor")


@dataclass(frozen=True)
class UploadInput:
    filename: str | None
    content_type: str | None
    data: bytes


class BatchProcessor:
    def __init__(self, *, processor: DocumentProcessor, db: Database, max_files: int) -> None:
        self._processor = processor
        self._db = db
        self._max_files = max_files

    def process_one(self, upload: UploadInput) -> DocumentResult:
        """Process a single file as its own run (used by POST /documents)."""
        run_id = uuid.uuid4().hex
        self._db.create_run(run_id, utc_now())
        results = self._process_all(run_id, [upload])
        return results[0]

    def process_files(self, uploads: Sequence[UploadInput]) -> BatchResult:
        """Process many files as one batch run with isolated per-file status."""
        if len(uploads) > self._max_files:
            raise BatchTooLargeError(
                f"batch of {len(uploads)} files exceeds the maximum of {self._max_files}"
            )
        run_id = uuid.uuid4().hex
        self._db.create_run(run_id, utc_now())
        results = self._process_all(run_id, list(uploads))
        failed = sum(1 for r in results if r.status is DocumentStatus.FAILED)
        needs_review = sum(1 for r in results if r.status is DocumentStatus.NEEDS_REVIEW)
        succeeded = len(results) - failed - needs_review
        return BatchResult(
            batch_id=run_id,
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            needs_review=needs_review,
            duplicates=sum(1 for r in results if r.duplicate),
            results=results,
        )

    # internals ------------------------------------------------------------

    def _process_all(
        self, run_id: str, uploads: Sequence[UploadInput]
    ) -> list[DocumentResult]:
        results: list[DocumentResult] = []
        for upload in uploads:
            try:
                result = self._processor.process_upload(
                    filename=upload.filename,
                    content_type=upload.content_type,
                    data=upload.data,
                    run_id=run_id,
                )
            except UploadError as exc:
                result = self._record_rejected_safely(run_id, upload, exc.code, exc.message)
            except Exception:
                # Defence in depth: even an unforeseen crash on one file is
                # reported as that file's failure instead of failing the batch.
                logger.exception("unexpected failure while processing an upload")
                result = self._record_rejected_safely(
                    run_id,
                    upload,
                    "processing_error",
                    "unexpected error while processing this file",
                )
            results.append(result)

        failed = sum(1 for r in results if r.status is DocumentStatus.FAILED)
        needs_review = sum(1 for r in results if r.status is DocumentStatus.NEEDS_REVIEW)
        succeeded = len(results) - failed - needs_review
        # Record what was uploaded onto the run (including duplicates, which by
        # design have no document row) so run reports can show every file.
        manifest = [
            {
                "original_filename": sanitise_filename(upload.filename),
                "document_id": result.document_id,
                "duplicate": result.duplicate,
            }
            for result, upload in zip(results, uploads, strict=True)
        ]
        self._db.finish_run(
            run_id,
            total=len(results),
            success=succeeded,
            failed=failed,
            needs_review=needs_review,
            finished_at=utc_now(),
            uploads=manifest,
        )
        return results

    def _record_rejected_safely(
        self, run_id: str, upload: UploadInput, code: str, message: str
    ) -> DocumentResult:
        """Persist the rejection; never let persistence itself break the batch."""
        try:
            return self._record_rejected(run_id, upload, code, message)
        except Exception:
            logger.exception("could not persist rejected upload")
            now = utc_now()
            return DocumentResult(
                document_id=uuid.uuid4().hex,
                original_filename=sanitise_filename(upload.filename),
                status=DocumentStatus.FAILED,
                file_size=len(upload.data),
                sha256=sha256_hex(upload.data),
                content_type=upload.content_type,
                error_message=f"{code}: {message}",
                run_id=run_id,
                created_at=now,
                updated_at=now,
            )

    def _record_rejected(
        self, run_id: str, upload: UploadInput, code: str, message: str
    ) -> DocumentResult:
        document_id = uuid.uuid4().hex
        now = utc_now()
        filename = sanitise_filename(upload.filename)
        self._db.insert_document(
            {
                "id": document_id,
                "original_filename": filename,
                "content_type": upload.content_type,
                "file_size": len(upload.data),
                "sha256": sha256_hex(upload.data),
                "status": DocumentStatus.FAILED.value,
                "storage_path": None,
                "run_id": run_id,
                "error_message": f"{code}: {message}",
                "created_at": now,
                "updated_at": now,
            }
        )
        return DocumentResult(
            document_id=document_id,
            original_filename=filename,
            status=DocumentStatus.FAILED,
            file_size=len(upload.data),
            sha256=sha256_hex(upload.data),
            content_type=upload.content_type,
            error_message=f"{code}: {message}",
            run_id=run_id,
            created_at=now,
            updated_at=now,
        )
