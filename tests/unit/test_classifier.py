"""Classification unit tests."""

from src.classification.classifier import DocumentClassifier
from src.models import Classification, DocumentType
from tests.conftest import (
    SAMPLE_INVOICE_TEXT,
    SAMPLE_MEMO_TEXT,
    SAMPLE_RECEIPT_TEXT,
)


class FakeLLMClassifier:
    def __init__(self, classification: Classification):
        self.classification = classification
        self.calls = 0

    def extract_invoice(self, text):  # pragma: no cover - not used here
        raise AssertionError("extract_invoice must not be called by the classifier")

    def classify(self, text) -> Classification:
        self.calls += 1
        return self.classification


class TestRulesClassification:
    def test_obvious_invoice(self):
        result = DocumentClassifier().classify(SAMPLE_INVOICE_TEXT)
        assert result.document_type is DocumentType.INVOICE
        assert result.method == "rules"
        assert result.confidence >= 0.5

    def test_obvious_receipt(self):
        result = DocumentClassifier().classify(SAMPLE_RECEIPT_TEXT)
        assert result.document_type is DocumentType.RECEIPT
        assert result.method == "rules"
        assert result.confidence >= 0.5

    def test_confidence_is_bounded(self):
        result = DocumentClassifier().classify(SAMPLE_INVOICE_TEXT * 20)
        assert 0.0 <= result.confidence <= 0.99

    def test_ambiguous_text_without_llm_falls_back_to_unknown(self):
        result = DocumentClassifier(llm_fallback=None).classify(SAMPLE_MEMO_TEXT)
        assert result.document_type is DocumentType.UNKNOWN
        assert result.confidence < 0.5


class TestLLMFallback:
    def test_llm_fallback_used_only_for_ambiguous_documents(self):
        fallback = FakeLLMClassifier(
            Classification(
                document_type=DocumentType.RECEIPT, confidence=0.87, method="llm"
            )
        )
        classifier = DocumentClassifier(llm_fallback=fallback)

        # Obvious invoice: rules decide, LLM never called.
        invoice = classifier.classify(SAMPLE_INVOICE_TEXT)
        assert invoice.method == "rules"
        assert fallback.calls == 0

        # Ambiguous memo: LLM consulted, its answer is used verbatim.
        memo = classifier.classify(SAMPLE_MEMO_TEXT)
        assert fallback.calls == 1
        assert memo.document_type is DocumentType.RECEIPT
        assert memo.method == "llm"
        assert memo.confidence == 0.87
