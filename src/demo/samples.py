"""Synthetic demo documents.

All company names, addresses, people and numbers below are invented for this
project. No real invoice, company or personal data is used anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

INVOICE_OK = """INVOICE
Demo Supplier Ltd.
14 Example Avenue
Springfield

Invoice Number: INV-1001
Invoice Date: 2026-09-01
Due Date: 2026-10-01

Bill To: Sample Customer Corp.

Description                          Qty   Unit Price    Amount
Consulting services (hours)           10        80.00    800.00
Software license (annual)              1       120.00    120.00

Subtotal: 920.00
Tax (10%): 92.00
Total: 1012.00

Currency: USD
Payment terms: Net 30
"""

INVOICE_MISSING_DUE_DATE = """INVOICE
Bright Office Supplies GmbH
Warehouse 3, 22 Industrial Way
Hamburg

Invoice Number: INV-2044
Invoice Date: 2026-09-15

Bill To: Example Studio LLC

Office chairs (x4)                     4        89.00    356.00
Next-day delivery                      1        94.00     94.00

Subtotal: 450.00
Tax: 45.00
Total: 495.00

Currency: EUR
"""

INVOICE_AMOUNT_MISMATCH = """INVOICE
Acme Paper Goods Co.
9 Commerce Street
Springfield

Invoice Number: INV-3007
Invoice Date: 2026-08-20
Due Date: 2026-09-19

Subtotal: 100.00
Tax: 10.00
Total: 999.00

Currency: USD
Thank you for your business.
"""

RECEIPT = """RECEIPT
Corner Cafe Demo
12 Market Street
Portland

Date: 2026-09-28
Card ending 4242

2 x Coffee                               7.00
1 x Bagel sandwich                       8.50

Total: 15.50
Currency: USD
Payment received - thank you!
"""

SCANNED_INVOICE = """INVOICE
Scanned Widgets Inc.
2 Illustration Way
Lakeview

Invoice Number: INV-5001
Invoice Date: 2026-09-10
Due Date: 2026-10-10

Subtotal: 200.00
Tax: 20.00
Total: 220.00

Currency: USD
"""

# Passes the %PDF- magic-byte check but is not a parseable document:
# demonstrates per-file failure isolation inside a batch.
CORRUPTED_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"\x00" * 512 + b"\ntrailer\n%%EOF\n"


def _write_text_pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()  # A4
    y = 72.0
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=11, fontname="helv")
        y += 16
    doc.save(path)
    doc.close()


def _write_image_pdf(path: Path, text: str) -> None:
    """A 'scanned' document: pixel image only, no text layer."""
    inner = pymupdf.open()
    page = inner.new_page()
    y = 72.0
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=12, fontname="helv")
        y += 18
    pix = page.get_pixmap(dpi=150)
    inner.close()

    outer = pymupdf.open()
    scanned_page = outer.new_page(width=pix.width, height=pix.height)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    outer.save(path)
    outer.close()


def generate_demo_documents(directory: Path) -> list[Path]:
    """Write the synthetic sample set; returns files in processing order."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    specs = [
        ("demo_invoice_ok.pdf", INVOICE_OK, _write_text_pdf),
        ("demo_invoice_missing_due_date.pdf", INVOICE_MISSING_DUE_DATE, _write_text_pdf),
        ("demo_invoice_amount_mismatch.pdf", INVOICE_AMOUNT_MISMATCH, _write_text_pdf),
        ("demo_receipt.pdf", RECEIPT, _write_text_pdf),
        ("demo_scanned_invoice.pdf", SCANNED_INVOICE, _write_image_pdf),
    ]
    paths = [directory / name for name, _, _ in specs]
    for path, (_, text, writer) in zip(paths, specs, strict=True):
        writer(path, text)

    corrupted = directory / "demo_corrupted.pdf"
    corrupted.write_bytes(CORRUPTED_BYTES)
    paths.append(corrupted)
    return paths
