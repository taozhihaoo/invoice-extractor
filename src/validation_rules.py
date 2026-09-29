"""Deterministic validation of extracted invoice data.

These checks verify the *internal consistency* of the extracted values only
(do the amounts add up, is the due date after the invoice date). They cannot
and do not verify that an invoice is genuine - that is out of scope and must
never be claimed.
"""

from __future__ import annotations

from decimal import Decimal

from .models import (
    DocumentType,
    ExtractionMethod,
    InvoiceData,
    ValidationResult,
)

# Allow small rounding differences: at least 2 cents, plus up to 0.1% of the
# total to absorb per-line rounding rules on larger amounts.
ABS_TOLERANCE = Decimal("0.02")
REL_TOLERANCE = Decimal("0.001")


def validate_invoice(invoice: InvoiceData) -> ValidationResult:
    warnings: list[str] = []

    if None not in (invoice.subtotal, invoice.tax, invoice.total):
        expected = invoice.subtotal + invoice.tax
        tolerance = max(ABS_TOLERANCE, REL_TOLERANCE * invoice.total)
        difference = abs(expected - invoice.total)
        if difference > tolerance:
            warnings.append(
                f"subtotal + tax ({expected:.2f}) does not match total ({invoice.total:.2f})"
            )

    if invoice.invoice_date and invoice.due_date and invoice.due_date < invoice.invoice_date:
        warnings.append(
            f"due_date ({invoice.due_date}) is before invoice_date ({invoice.invoice_date})"
        )

    return ValidationResult(passed=not warnings, warnings=warnings)


def missing_fields(invoice: InvoiceData) -> list[str]:
    from .models.invoice import FIELDS

    return [name for name in FIELDS if getattr(invoice, name) is None]


def build_review_reasons(
    *,
    document_type: DocumentType,
    extraction_method: ExtractionMethod,
    ocr_available: bool,
    invoice: InvoiceData | None,
    validation: ValidationResult | None,
) -> list[str]:
    """Human-readable reasons why a document needs manual review."""
    reasons: list[str] = []

    if extraction_method is ExtractionMethod.NONE:
        suffix = "" if ocr_available else " (OCR engine not installed)"
        reasons.append(f"no extractable text{suffix}")

    if document_type is DocumentType.UNKNOWN:
        reasons.append("document type could not be determined")

    if document_type is DocumentType.INVOICE and invoice is not None:
        missing = missing_fields(invoice)
        if missing:
            reasons.append("fields could not be extracted: " + ", ".join(missing))
        if validation is not None and not validation.passed:
            reasons.extend(validation.warnings)

    return reasons
