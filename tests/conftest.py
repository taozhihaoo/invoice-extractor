"""Shared fixtures and PDF factories.

All tests run fully offline: the LLM provider is forced to ``mock`` and no
test ever opens a network connection.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import Settings

SAMPLE_INVOICE_TEXT = """INVOICE
Test Supplier GmbH
Warehouse 3, 22 Industrial Way
Hamburg

Invoice Number: INV-9001
Invoice Date: 2026-09-01
Due Date: 2026-10-01

Bill To: Example Buyer Oy

Subtotal: 100.00
Tax: 20.00
Total: 120.00

Currency: EUR
"""

SAMPLE_INVOICE_MISSING_DUE_DATE = SAMPLE_INVOICE_TEXT.replace(
    "Due Date: 2026-10-01\n", ""
)

SAMPLE_INVOICE_MISMATCH = """INVOICE
Mismatch Goods Co.
Invoice Number: INV-9002
Invoice Date: 2026-08-20
Due Date: 2026-09-19

Subtotal: 100.00
Tax: 10.00
Total: 999.00

Currency: USD
"""

SAMPLE_RECEIPT_TEXT = """RECEIPT
Corner Cafe Demo
Date: 2026-09-28
Card ending 4242
2 x Coffee 7.00
1 x Bagel 8.50
Total: 15.50
Currency: USD
Payment received - thank you!
"""

SAMPLE_MEMO_TEXT = """Internal memo
Please send the invoice to accounting when it arrives.
Nothing else to see here.
"""

CORRUPTED_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 512 + b"\ntrailer\n%%EOF\n"


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        database_path=tmp_path / "processor.db",
        upload_dir=tmp_path / "uploads",
        export_dir=tmp_path / "exports",
        llm_provider="mock",
    )
    values.update(overrides)
    return Settings(**values)


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=11, fontname="helv")
        y += 16
    data = doc.tobytes()
    doc.close()
    return data


def make_multipage_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        y = 72.0
        for line in text.splitlines():
            page.insert_text((72, y), line if line else " ", fontsize=11, fontname="helv")
            y += 16
    data = doc.tobytes()
    doc.close()
    return data


def make_image_only_pdf(text: str) -> bytes:
    """A 'scanned' PDF: one page containing only a raster image, no text layer."""
    inner = pymupdf.open()
    page = inner.new_page()
    y = 72.0
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=12, fontname="helv")
        y += 18
    pix = page.get_pixmap(dpi=120)
    inner.close()
    outer = pymupdf.open()
    image_page = outer.new_page(width=pix.width, height=pix.height)
    image_page.insert_image(image_page.rect, pixmap=pix)
    data = outer.tobytes()
    outer.close()
    return data


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    # raise_server_exceptions=False lets the app's own 500 handler produce the
    # response clients actually receive.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def upload_pdf(client, data: bytes, name: str = "doc.pdf", content_type: str = "application/pdf"):
    return client.post(
        "/documents", files={"file": (name, data, content_type)}
    )
