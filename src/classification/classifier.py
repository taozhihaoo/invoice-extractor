"""Two-stage classification.

Stage 1 is a deterministic weighted-keyword scorer: obvious invoices and
receipts are classified in pure Python with a confidence derived from the
matched evidence (never a made-up number). Stage 2 (optional) delegates only
ambiguous documents to the LLM client, which returns its own confidence.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..models import Classification, DocumentType

if TYPE_CHECKING:
    from ..llm.base import LLMClient

INVOICE_SIGNALS: dict[str, float] = {
    "invoice": 0.35,
    "invoice number": 0.20,
    "invoice no": 0.20,
    "invoice #": 0.20,
    "bill to": 0.15,
    "due date": 0.15,
    "payment terms": 0.10,
    "purchase order": 0.10,
    "remit to": 0.10,
}

RECEIPT_SIGNALS: dict[str, float] = {
    "receipt": 0.40,
    "cash receipt": 0.20,
    "sales receipt": 0.20,
    "payment received": 0.20,
    "thank you for your purchase": 0.20,
    "change due": 0.15,
    "card ending": 0.15,
}

RULE_CONFIDENCE_THRESHOLD = 0.5
MAX_CONFIDENCE = 0.99


def _signal_pattern(phrase: str) -> str:
    escaped = re.escape(phrase)
    head = r"\b" if phrase[0].isalnum() else ""
    tail = r"\b" if phrase[-1].isalnum() else ""
    return head + escaped + tail


def score_signals(text: str, signals: dict[str, float]) -> float:
    score = 0.0
    for phrase, weight in signals.items():
        if re.search(_signal_pattern(phrase), text, re.IGNORECASE):
            score += weight
    return min(score, MAX_CONFIDENCE)


class DocumentClassifier:
    def __init__(
        self,
        llm_fallback: LLMClient | None = None,
        threshold: float = RULE_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._llm_fallback = llm_fallback
        self._threshold = threshold

    def classify(self, text: str) -> Classification:
        invoice_score = score_signals(text, INVOICE_SIGNALS)
        receipt_score = score_signals(text, RECEIPT_SIGNALS)

        if invoice_score >= receipt_score:
            best_type, best_score = DocumentType.INVOICE, invoice_score
        else:
            best_type, best_score = DocumentType.RECEIPT, receipt_score

        if best_score >= self._threshold:
            return Classification(
                document_type=best_type,
                confidence=round(best_score, 2),
                method="rules",
            )

        if self._llm_fallback is not None:
            return self._llm_fallback.classify(text)

        return Classification(
            document_type=DocumentType.UNKNOWN,
            confidence=round(best_score, 2),
            method="rules",
        )
