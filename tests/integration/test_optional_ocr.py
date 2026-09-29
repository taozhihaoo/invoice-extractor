"""Real OCR integration test.

Runs only when a Tesseract binary is actually installed; skipped everywhere
else (including CI, which does not install Tesseract).
"""

import shutil

import pytest

from src.bootstrap import build
from src.models import DocumentStatus
from tests.conftest import SAMPLE_INVOICE_TEXT, make_image_only_pdf, make_settings

pytestmark = [
    pytest.mark.optional_ocr,
    pytest.mark.skipif(
        shutil.which("tesseract") is None,
        reason="Tesseract is not installed on this machine",
    ),
]


def test_scanned_invoice_is_extracted_with_real_ocr(tmp_path):
    settings = make_settings(tmp_path)
    components = build(settings)
    result = components.processor.process_upload(
        filename="scanned.pdf",
        content_type="application/pdf",
        data=make_image_only_pdf(SAMPLE_INVOICE_TEXT),
    )
    assert result.extraction_method.value == "ocr"
    assert result.extraction.invoice.invoice_number == "INV-9001"
    assert result.status is DocumentStatus.PROCESSED
