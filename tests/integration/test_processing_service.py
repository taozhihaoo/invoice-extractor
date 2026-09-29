"""Processing service and batch integration tests (mock LLM, offline)."""

import pytest

from src.bootstrap import build
from src.errors import BatchTooLargeError
from src.models import DocumentStatus, DocumentType
from src.processing import UploadInput
from tests.conftest import (
    CORRUPTED_PDF_BYTES,
    SAMPLE_INVOICE_MISMATCH,
    SAMPLE_INVOICE_MISSING_DUE_DATE,
    SAMPLE_INVOICE_TEXT,
    SAMPLE_MEMO_TEXT,
    SAMPLE_RECEIPT_TEXT,
    make_image_only_pdf,
    make_pdf,
    make_settings,
)


@pytest.fixture
def components(settings):
    return build(settings)


def upload_input(data: bytes, name: str = "doc.pdf") -> UploadInput:
    return UploadInput(filename=name, content_type="application/pdf", data=data)


class TestSingleDocument:
    def test_complete_invoice_is_processed(self, components):
        result = components.processor.process_upload(
            filename="invoice.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_INVOICE_TEXT),
        )
        assert result.status is DocumentStatus.PROCESSED
        assert result.document_type is DocumentType.INVOICE
        assert result.extraction.invoice.invoice_number == "INV-9001"
        assert result.extraction.validation.passed
        assert result.review_reasons == []
        assert result.page_count == 1
        assert result.extraction_method.value == "native_text"

    def test_missing_field_marks_needs_review(self, components):
        result = components.processor.process_upload(
            filename="invoice.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_INVOICE_MISSING_DUE_DATE),
        )
        assert result.status is DocumentStatus.NEEDS_REVIEW
        assert any("due_date" in reason for reason in result.review_reasons)

    def test_amount_mismatch_marks_needs_review(self, components):
        result = components.processor.process_upload(
            filename="invoice.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_INVOICE_MISMATCH),
        )
        assert result.status is DocumentStatus.NEEDS_REVIEW
        assert result.extraction.validation.passed is False
        assert any("does not match total" in reason for reason in result.review_reasons)

    def test_receipt_processed_without_invoice_extraction(self, components):
        result = components.processor.process_upload(
            filename="receipt.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_RECEIPT_TEXT),
        )
        assert result.status is DocumentStatus.PROCESSED
        assert result.document_type is DocumentType.RECEIPT
        assert result.extraction is None

    def test_unknown_document_needs_review(self, components):
        result = components.processor.process_upload(
            filename="memo.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_MEMO_TEXT),
        )
        assert result.status is DocumentStatus.NEEDS_REVIEW
        assert result.document_type is DocumentType.UNKNOWN
        assert any("document type" in reason for reason in result.review_reasons)

    def test_corrupted_pdf_fails_without_crashing(self, components):
        result = components.processor.process_upload(
            filename="corrupt.pdf", content_type="application/pdf",
            data=CORRUPTED_PDF_BYTES,
        )
        assert result.status is DocumentStatus.FAILED
        assert result.error_message and "invalid_pdf" in result.error_message
        assert result.extraction is None

    def test_image_only_pdf_without_ocr_needs_review(self, components):
        result = components.processor.process_upload(
            filename="scanned.pdf", content_type="application/pdf",
            data=make_image_only_pdf(SAMPLE_INVOICE_TEXT),
        )
        assert result.status is DocumentStatus.NEEDS_REVIEW
        assert result.extraction_method.value == "none"
        assert any("no extractable text" in reason for reason in result.review_reasons)

    def test_upload_rejection_raises(self, components):
        from src.errors import UnsupportedFileTypeError

        with pytest.raises(UnsupportedFileTypeError):
            components.processor.process_upload(
                filename="virus.exe", content_type="application/octet-stream",
                data=b"MZ fake binary",
            )


class TestDuplicates:
    def test_same_bytes_processed_once(self, components):
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        first = components.processor.process_upload(
            filename="a.pdf", content_type="application/pdf", data=data
        )
        second = components.processor.process_upload(
            filename="b.pdf", content_type="application/pdf", data=data
        )
        assert not first.duplicate
        assert second.duplicate
        assert second.duplicate_of == first.document_id
        assert second.document_id == first.document_id
        assert second.extraction.invoice.invoice_number == "INV-9001"

    def test_duplicate_does_not_call_the_llm_again(self, components):
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        components.processor.process_upload(
            filename="a.pdf", content_type="application/pdf", data=data
        )
        calls_before = components.llm.invoice_calls
        components.processor.process_upload(
            filename="b.pdf", content_type="application/pdf", data=data
        )
        assert components.llm.invoice_calls == calls_before

    def test_different_bytes_are_not_duplicates(self, components):
        components.processor.process_upload(
            filename="a.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_INVOICE_TEXT),
        )
        other = components.processor.process_upload(
            filename="b.pdf", content_type="application/pdf",
            data=make_pdf(SAMPLE_INVOICE_MISMATCH),
        )
        assert not other.duplicate


class TestBatch:
    def test_batch_isolates_failures(self, components):
        uploads = [
            upload_input(make_pdf(SAMPLE_INVOICE_TEXT), "ok.pdf"),
            upload_input(CORRUPTED_PDF_BYTES, "corrupt.pdf"),
            upload_input(make_pdf(SAMPLE_RECEIPT_TEXT), "receipt.pdf"),
        ]
        result = components.batch.process_files(uploads)
        assert result.total == 3
        assert result.succeeded == 2
        assert result.failed == 1
        assert result.needs_review == 0
        statuses = [r.status for r in result.results]
        assert statuses == [
            DocumentStatus.PROCESSED, DocumentStatus.FAILED, DocumentStatus.PROCESSED,
        ]
        # Every file belongs to the same run.
        assert {r.run_id for r in result.results} == {result.batch_id}
        # The run record in the database matches.
        run = components.db.get_run(result.batch_id)
        assert (run["total"], run["success"], run["failed"]) == (3, 2, 1)

    def test_mixed_batch_counts(self, components):
        uploads = [
            upload_input(make_pdf(SAMPLE_INVOICE_TEXT), "ok.pdf"),
            upload_input(make_pdf(SAMPLE_INVOICE_MISSING_DUE_DATE), "missing.pdf"),
            upload_input(make_pdf(SAMPLE_INVOICE_MISMATCH), "mismatch.pdf"),
            upload_input(CORRUPTED_PDF_BYTES, "corrupt.pdf"),
        ]
        result = components.batch.process_files(uploads)
        assert (result.total, result.succeeded, result.needs_review, result.failed) == (4, 1, 2, 1)

    def test_rejected_file_recorded_as_failed_in_batch(self, components):
        uploads = [
            upload_input(make_pdf(SAMPLE_INVOICE_TEXT), "ok.pdf"),
            UploadInput(filename="notes.txt", content_type="text/plain", data=b"not a pdf"),
        ]
        result = components.batch.process_files(uploads)
        assert result.failed == 1
        rejected = result.results[1]
        assert rejected.status is DocumentStatus.FAILED
        assert "unsupported_file_type" in rejected.error_message
        # The rejection is persisted so batch reports stay complete.
        row = components.db.get_document(rejected.document_id)
        assert row["status"] == "failed"

    def test_duplicate_inside_one_batch(self, components):
        data = make_pdf(SAMPLE_INVOICE_TEXT)
        result = components.batch.process_files(
            [upload_input(data, "first.pdf"), upload_input(data, "second.pdf")]
        )
        assert result.duplicates == 1
        assert result.results[1].duplicate
        assert result.results[0].document_id == result.results[1].document_id

    def test_batch_size_limit(self, tmp_path):
        components = build(make_settings(tmp_path, max_batch_files=2))
        with pytest.raises(BatchTooLargeError):
            components.batch.process_files(
                [upload_input(CORRUPTED_PDF_BYTES, "x.pdf")] * 3
            )


class TestSingleFileRun:
    def test_process_one_creates_a_run(self, components):
        result = components.batch.process_one(upload_input(make_pdf(SAMPLE_INVOICE_TEXT)))
        assert result.run_id
        run = components.db.get_run(result.run_id)
        assert run["total"] == 1
        assert run["success"] == 1


class TestBuilder:
    def test_build_uses_mock_without_key(self, tmp_path):
        settings = make_settings(tmp_path, llm_provider="auto")
        components = build(settings)
        assert components.llm_provider == "mock"

    def test_build_openai_without_key_raises(self, tmp_path):
        from src.errors import ConfigurationError

        settings = make_settings(tmp_path, llm_provider="openai", openai_api_key=None)
        with pytest.raises(ConfigurationError):
            build(settings)
