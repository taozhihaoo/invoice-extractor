"""Structured invoice data.

``None`` always means "not present in the document". The extraction layer
(whether a real LLM or the deterministic mock) must never invent values for
missing information - that rule is enforced here by allowing nullable fields
and rejecting malformed ones.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Accepted printed formats; values are normalised to ISO 8601 (YYYY-MM-DD).
# Day-first is assumed for numeric DD/MM/YYYY (documented assumption).
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)

FIELDS = (
    "supplier",
    "invoice_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax",
    "total",
    "currency",
)


class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier: str | None = Field(default=None, max_length=256)
    invoice_number: str | None = Field(default=None, max_length=64)
    invoice_date: str | None = None
    due_date: str | None = None
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("supplier", "invoice_number", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def _normalise_date(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            text = value.strip()
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(text, fmt).date().isoformat()
                except ValueError:
                    continue
            raise ValueError(
                f"unrecognised date format {text!r}; expected e.g. 2026-09-01"
            )
        raise ValueError("date must be a string or null")

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def _to_decimal(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, str):
            text = value.strip().replace(",", "").replace(" ", "").strip("$€£")
            if not text:
                return None
            value = text
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"amount must be a number, got {value!r}") from exc

    @field_validator("currency", mode="before")
    @classmethod
    def _clean_currency(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, str):
            return value.strip().upper()
        return value
