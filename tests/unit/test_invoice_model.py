"""InvoiceData schema validation tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.models import InvoiceData


class TestDates:
    def test_iso_date_accepted(self):
        data = InvoiceData(invoice_date="2026-09-01")
        assert data.invoice_date == "2026-09-01"

    def test_european_date_normalised(self):
        assert InvoiceData(invoice_date="01.09.2026").invoice_date == "2026-09-01"
        assert InvoiceData(due_date="01/10/2026").due_date == "2026-10-01"

    def test_written_month_normalised(self):
        assert InvoiceData(invoice_date="September 1, 2026").invoice_date == "2026-09-01"

    def test_invalid_date_rejected(self):
        with pytest.raises(ValidationError):
            InvoiceData(invoice_date="not a date at all")

    def test_empty_string_becomes_none(self):
        assert InvoiceData(invoice_date="").invoice_date is None


class TestAmounts:
    def test_numbers_accepted(self):
        data = InvoiceData(subtotal=100, tax=20.5, total="120.50")
        assert data.subtotal == Decimal("100")
        assert data.tax == Decimal("20.5")
        assert data.total == Decimal("120.50")

    def test_formatted_string_amount_normalised(self):
        assert InvoiceData(subtotal="1,234.50").subtotal == Decimal("1234.50")
        assert InvoiceData(total="$ 99.00").total == Decimal("99.00")

    def test_non_numeric_amount_rejected(self):
        with pytest.raises(ValidationError):
            InvoiceData(total="twelve euros")

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            InvoiceData(total=-5)

    def test_empty_amount_becomes_none(self):
        assert InvoiceData(tax="") .tax is None


class TestCurrency:
    def test_lowercased_input_normalised(self):
        assert InvoiceData(currency="usd").currency == "USD"

    def test_invalid_code_rejected(self):
        with pytest.raises(ValidationError):
            InvoiceData(currency="USDD")

    def test_empty_becomes_none(self):
        assert InvoiceData(currency="  ").currency is None


class TestMissingFields:
    def test_all_fields_optional(self):
        data = InvoiceData()
        for name in (
            "supplier", "invoice_number", "invoice_date", "due_date",
            "subtotal", "tax", "total", "currency",
        ):
            assert getattr(data, name) is None

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            InvoiceData(surprise_field="nope")

    def test_blank_text_becomes_none_not_empty_string(self):
        assert InvoiceData(supplier="   ").supplier is None
