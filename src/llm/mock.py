"""Deterministic, offline implementation of :class:`LLMClient`.

Used by demo mode, the test-suite and as the automatic fallback when no API
key is configured. Field extraction uses labelled regex patterns; a field the
patterns cannot find is returned as ``None`` - the mock never guesses either.
Call counters are exposed so tests can prove the LLM was (not) invoked.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from ..classification.classifier import (
    INVOICE_SIGNALS,
    RECEIPT_SIGNALS,
    RULE_CONFIDENCE_THRESHOLD,
    score_signals,
)
from ..models import Classification, DocumentType, Usage
from .base import InvoiceExtractionResult
from .schemas import SYSTEM_CLASSIFY_PROMPT  # noqa: F401  (kept for parity/docs)

_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?"
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
_ISO_CURRENCIES = {
    "USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "PLN", "CNY", "INR",
}
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


def _parse_date(raw: str) -> str | None:
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None  # unparseable -> None, never a guess


def _labelled_date(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{label}\s*[:\-]\s*(.+?)\s*$", text)
    return _parse_date(match.group(1)) if match else None


def _money(text: str, label: str) -> Decimal | None:
    pattern = (
        rf"(?im)^\s*{label}\s*[:\-]?\s*(?:USD|EUR|GBP|CHF)?\s*[$€£]?\s*"
        rf"{_AMOUNT}\s*(?:USD|EUR|GBP|CHF)?\s*$"
    )
    match = re.search(pattern, text)
    if not match:
        return None
    whole = match.group(1).replace(",", "")
    cents = match.group(2) or "00"
    return Decimal(f"{whole}.{cents}")


def _invoice_number(text: str) -> str | None:
    match = re.search(
        r"(?im)^\s*invoice\s*(?:number|no\.?|num|#)?\s*[:#]\s*#?\s*"
        r"([A-Za-z0-9][A-Za-z0-9/\-]*)\s*$",
        text,
    )
    if match:
        return match.group(1)
    match = re.search(r"\b(INV[-\s]?\d{3,})\b", text, re.IGNORECASE)
    if match:
        return re.sub(r"\s+", "-", match.group(1)).upper()
    return None


def _supplier(text: str) -> str | None:
    match = re.search(r"(?im)^\s*(?:supplier|vendor|from)\s*[:\-]\s*(.+?)\s*$", text)
    if match:
        return match.group(1)
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if re.fullmatch(r"(?i)\s*(tax\s+)?(invoice|receipt)\s*", line) and index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if candidate and not re.match(
                r"(?i)^(invoice|due|date|bill|supplier|from|customer)\b", candidate
            ):
                return candidate
    return None


def _currency(text: str) -> str | None:
    match = re.search(r"(?im)^\s*currenc(?:y|ies)\s*[:\-]?\s*([A-Za-z]{3})\s*$", text)
    if match and match.group(1).upper() in _ISO_CURRENCIES:
        return match.group(1).upper()
    match = re.search(r"\b(USD|EUR|GBP|CHF|JPY|CAD|AUD|NZD)\b", text)
    if match:
        return match.group(1)
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    return None


def extract_invoice_fields(text: str) -> dict[str, object]:
    """Deterministic labelled-pattern extraction; missing fields stay None."""
    return {
        "supplier": _supplier(text),
        "invoice_number": _invoice_number(text),
        "invoice_date": _labelled_date(text, r"invoice\s*date"),
        "due_date": _labelled_date(text, r"due\s*date"),
        "subtotal": _money(text, r"sub[\s\-]?total"),
        "tax": _money(text, r"tax(?:\s*\([^)]*\))?"),
        "total": _money(text, r"total(?:\s*\([^)]*\))?"),
        "currency": _currency(text),
    }


class MockLLMClient:
    provider = "mock"
    model = "mock-rules-v1"

    def __init__(self) -> None:
        self.invoice_calls = 0
        self.classify_calls = 0

    def extract_invoice(self, text: str) -> InvoiceExtractionResult:
        self.invoice_calls += 1
        from ..models import InvoiceData

        data = extract_invoice_fields(text)
        return InvoiceExtractionResult(
            invoice=InvoiceData(**data),  # type: ignore[arg-type]
            usage=Usage(),
            model=self.model,
        )

    def classify(self, text: str) -> Classification:
        self.classify_calls += 1
        invoice_score = score_signals(text, INVOICE_SIGNALS)
        receipt_score = score_signals(text, RECEIPT_SIGNALS)
        if max(invoice_score, receipt_score) >= RULE_CONFIDENCE_THRESHOLD:
            doc_type = (
                DocumentType.INVOICE if invoice_score >= receipt_score else DocumentType.RECEIPT
            )
            return Classification(
                document_type=doc_type,
                confidence=round(max(invoice_score, receipt_score), 2),
                method="llm",
            )
        return Classification(
            document_type=DocumentType.UNKNOWN,
            confidence=round(max(invoice_score, receipt_score), 2),
            method="llm",
        )
