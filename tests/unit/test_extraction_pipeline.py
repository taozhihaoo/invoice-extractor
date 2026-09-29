"""Extraction pipeline unit tests."""

import pytest

from src.errors import InvalidPdfError, TooManyPagesError
from src.extraction.base import ExtractedDocument
from src.extraction.ocr import OcrUnavailableError
from src.extraction.pipeline import ExtractionPipeline, normalise_text
from tests.conftest import (
    SAMPLE_INVOICE_TEXT,
    make_image_only_pdf,
    make_multipage_pdf,
    make_pdf,
)


class FakeOcr:
    """Stands in for OcrExtractor in tests; never touches Tesseract."""

    def __init__(self, text: str, available: bool = True):
        self.text = text
        self._available = available
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def extract_pages(self, pdf_path, page_indices):
        self.calls += 1
        return [self.text for _ in page_indices]


def pipeline(**kwargs) -> ExtractionPipeline:
    values = dict(max_pages=50, min_text_chars=100, ocr=None)
    values.update(kwargs)
    return ExtractionPipeline(**values)


class TestNativeExtraction:
    def test_extracts_text_from_native_pdf(self, tmp_path):
        path = tmp_path / "invoice.pdf"
        path.write_bytes(make_pdf(SAMPLE_INVOICE_TEXT))
        result = pipeline().extract(path)
        assert "INV-9001" in result.text
        assert result.page_count == 1
        assert result.method.value == "native_text"
        assert result.text_length > 100

    def test_counts_multiple_pages(self, tmp_path):
        path = tmp_path / "multi.pdf"
        path.write_bytes(make_multipage_pdf(["Page one " + "x " * 80, "Page two"]))
        result = pipeline().extract(path)
        assert result.page_count == 2

    def test_text_is_normalised(self):
        raw = "Line one   with\tspaces\r\n\r\nLine two"
        cleaned = normalise_text(raw)
        assert cleaned == "Line one with spaces\nLine two"

    def test_corrupted_pdf_raises_invalid_pdf(self, tmp_path):
        path = tmp_path / "bad.pdf"
        path.write_bytes(b"%PDF-1.7\n" + b"\x00" * 512 + b"trailer\n%%EOF\n")
        with pytest.raises(InvalidPdfError):
            pipeline().extract(path)


class TestPageLimits:
    def test_too_many_pages_rejected(self, tmp_path):
        path = tmp_path / "big.pdf"
        path.write_bytes(make_multipage_pdf(["p1", "p2", "p3"]))
        with pytest.raises(TooManyPagesError):
            pipeline(max_pages=2).extract(path)


class TestOcrFallback:
    def test_image_only_pdf_without_ocr_has_no_text(self, tmp_path):
        path = tmp_path / "scanned.pdf"
        path.write_bytes(make_image_only_pdf(SAMPLE_INVOICE_TEXT))
        result = pipeline(ocr=None).extract(path)
        assert result.text == ""
        assert result.method.value == "none"

    def test_image_only_pdf_uses_ocr_when_available(self, tmp_path):
        path = tmp_path / "scanned.pdf"
        path.write_bytes(make_image_only_pdf(SAMPLE_INVOICE_TEXT))
        fake = FakeOcr(SAMPLE_INVOICE_TEXT)
        result = pipeline(ocr=fake).extract(path)
        assert "INV-9001" in result.text
        assert result.method.value == "ocr"
        assert fake.calls == 1

    def test_ocr_not_used_when_native_text_is_sufficient(self, tmp_path):
        path = tmp_path / "invoice.pdf"
        path.write_bytes(make_pdf(SAMPLE_INVOICE_TEXT))
        fake = FakeOcr("should not be used")
        result = pipeline(ocr=fake).extract(path)
        assert result.method.value == "native_text"
        assert fake.calls == 0

    def test_ocr_unavailable_is_reported_honestly(self, tmp_path):
        path = tmp_path / "scanned.pdf"
        path.write_bytes(make_image_only_pdf(SAMPLE_INVOICE_TEXT))
        fake = FakeOcr(SAMPLE_INVOICE_TEXT, available=False)
        result = pipeline(ocr=fake).extract(path)
        assert result.method.value == "none"
        assert fake.calls == 0

    def test_extracted_document_length_property(self):
        doc = ExtractedDocument(text="hello", page_count=1, method=None)
        assert doc.text_length == 5


class TestOcrUnavailableError:
    def test_error_message_mentions_tesseract(self):
        assert "Tesseract" in str(OcrUnavailableError("Tesseract OCR engine is not installed"))
