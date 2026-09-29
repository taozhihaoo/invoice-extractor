"""Deterministic validation rules tests."""


from src.models import DocumentType, ExtractionMethod, InvoiceData
from src.validation_rules import build_review_reasons, validate_invoice


def invoice(**kwargs) -> InvoiceData:
    return InvoiceData(**kwargs)


class TestAmountConsistency:
    def test_matching_amounts_pass(self):
        result = validate_invoice(
            invoice(subtotal="920.00", tax="92.00", total="1012.00")
        )
        assert result.passed
        assert result.warnings == []

    def test_mismatch_produces_warning(self):
        result = validate_invoice(invoice(subtotal="100.00", tax="10.00", total="999.00"))
        assert not result.passed
        assert any("does not match total" in w for w in result.warnings)

    def test_small_rounding_difference_is_tolerated(self):
        result = validate_invoice(invoice(subtotal="33.33", tax="6.68", total="40.00"))
        assert result.passed

    def test_relative_tolerance_on_large_amounts(self):
        # Difference 0.40 on a 1000 total stays inside the 0.1% tolerance (1.00).
        result = validate_invoice(invoice(subtotal="900.00", tax="100.40", total="1000.00"))
        assert result.passed
        # Difference 3.00 exceeds it.
        result = validate_invoice(invoice(subtotal="900.00", tax="103.00", total="1000.00"))
        assert not result.passed

    def test_missing_amounts_skip_the_check(self):
        assert validate_invoice(invoice(subtotal="100.00")).passed
        assert validate_invoice(invoice(total="100.00")).passed


class TestDateOrdering:
    def test_due_date_before_invoice_date_warns(self):
        result = validate_invoice(
            invoice(invoice_date="2026-10-01", due_date="2026-09-01")
        )
        assert not result.passed
        assert any("before invoice_date" in w for w in result.warnings)

    def test_same_dates_pass(self):
        result = validate_invoice(
            invoice(invoice_date="2026-09-01", due_date="2026-09-01")
        )
        assert result.passed

    def test_partial_dates_skip_the_check(self):
        assert validate_invoice(invoice(invoice_date="2026-09-01")).passed
        assert validate_invoice(invoice(due_date="2026-09-01")).passed


class TestReviewReasons:
    def test_no_text_reason_mentions_ocr_when_unavailable(self):
        reasons = build_review_reasons(
            document_type=DocumentType.UNKNOWN,
            extraction_method=ExtractionMethod.NONE,
            ocr_available=False,
            invoice=None,
            validation=None,
        )
        assert any("no extractable text" in r and "OCR" in r for r in reasons)

    def test_no_text_reason_without_ocr_note_when_available(self):
        reasons = build_review_reasons(
            document_type=DocumentType.INVOICE,
            extraction_method=ExtractionMethod.NONE,
            ocr_available=True,
            invoice=None,
            validation=None,
        )
        assert any("no extractable text" in r for r in reasons)
        assert not any("OCR engine not installed" in r for r in reasons)

    def test_unknown_type_reason(self):
        reasons = build_review_reasons(
            document_type=DocumentType.UNKNOWN,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            ocr_available=False,
            invoice=None,
            validation=None,
        )
        assert any("document type" in r for r in reasons)

    def test_missing_fields_listed(self):
        reasons = build_review_reasons(
            document_type=DocumentType.INVOICE,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            ocr_available=True,
            invoice=invoice(invoice_number="INV-1"),
            validation=None,
        )
        joined = "; ".join(reasons)
        assert "due_date" in joined
        assert "invoice_date" in joined
        assert "invoice_number" not in joined  # it was extracted

    def test_validation_warnings_become_review_reasons(self):
        validation = validate_invoice(invoice(subtotal="1.00", tax="1.00", total="500.00"))
        reasons = build_review_reasons(
            document_type=DocumentType.INVOICE,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            ocr_available=True,
            invoice=invoice(subtotal="1.00", tax="1.00", total="500.00"),
            validation=validation,
        )
        assert any("does not match total" in r for r in reasons)

    def test_clean_invoice_has_no_reasons(self):
        good = invoice(
            supplier="A", invoice_number="INV-1", invoice_date="2026-09-01",
            due_date="2026-10-01", subtotal="100.00", tax="20.00", total="120.00",
            currency="EUR",
        )
        reasons = build_review_reasons(
            document_type=DocumentType.INVOICE,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            ocr_available=True,
            invoice=good,
            validation=validate_invoice(good),
        )
        assert reasons == []
