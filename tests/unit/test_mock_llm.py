"""MockLLMClient tests: the demo engine must extract correctly and never guess."""

from decimal import Decimal

from src.llm.mock import MockLLMClient
from src.models import DocumentType
from tests.conftest import (
    SAMPLE_INVOICE_MISSING_DUE_DATE,
    SAMPLE_INVOICE_TEXT,
    SAMPLE_MEMO_TEXT,
    SAMPLE_RECEIPT_TEXT,
)


class TestExtractInvoice:
    def test_extracts_all_fields_from_complete_invoice(self):
        result = MockLLMClient().extract_invoice(SAMPLE_INVOICE_TEXT)
        invoice = result.invoice
        assert invoice.supplier == "Test Supplier GmbH"
        assert invoice.invoice_number == "INV-9001"
        assert invoice.invoice_date == "2026-09-01"
        assert invoice.due_date == "2026-10-01"
        assert invoice.subtotal == Decimal("100.00")
        assert invoice.tax == Decimal("20.00")
        assert invoice.total == Decimal("120.00")
        assert invoice.currency == "EUR"

    def test_missing_field_is_none_not_a_guess(self):
        result = MockLLMClient().extract_invoice(SAMPLE_INVOICE_MISSING_DUE_DATE)
        assert result.invoice.due_date is None
        assert result.invoice.invoice_number == "INV-9001"  # the rest still extracts

    def test_unrelated_text_yields_all_none(self):
        result = MockLLMClient().extract_invoice(
            "The quick brown fox jumps over the lazy dog."
        )
        assert result.invoice.supplier is None
        assert result.invoice.total is None
        assert result.invoice.currency is None

    def test_usage_is_zero_for_mock(self):
        result = MockLLMClient().extract_invoice(SAMPLE_INVOICE_TEXT)
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.model == "mock-rules-v1"

    def test_amount_with_thousands_separator(self):
        text = (
            "INVOICE\nAcme Co\nInvoice Number: INV-7777\n"
            "Subtotal: 1,234.50\nTax: 0.00\nTotal: 1,234.50\n"
        )
        invoice = MockLLMClient().extract_invoice(text).invoice
        assert invoice.subtotal == Decimal("1234.50")
        assert invoice.total == Decimal("1234.50")


class TestClassify:
    def test_invoice_text(self):
        result = MockLLMClient().classify(SAMPLE_INVOICE_TEXT)
        assert result.document_type is DocumentType.INVOICE

    def test_receipt_text(self):
        result = MockLLMClient().classify(SAMPLE_RECEIPT_TEXT)
        assert result.document_type is DocumentType.RECEIPT

    def test_unknown_text(self):
        result = MockLLMClient().classify(SAMPLE_MEMO_TEXT)
        assert result.document_type is DocumentType.UNKNOWN


class TestCallCounters:
    def test_counters_increment(self):
        client = MockLLMClient()
        client.extract_invoice(SAMPLE_INVOICE_TEXT)
        client.classify(SAMPLE_INVOICE_TEXT)
        assert client.invoice_calls == 1
        assert client.classify_calls == 1
