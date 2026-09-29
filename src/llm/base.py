"""LLMClient protocol plus a provider-agnostic error hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import Classification, InvoiceData, Usage


class LLMError(Exception):
    """Base class for LLM failures; messages are safe to store/log."""

    code = "llm_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = type(self).code


class LLMAuthError(LLMError):
    code = "llm_auth_error"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limit"


class LLMTimeoutError(LLMError):
    code = "llm_timeout"


class LLMAPIError(LLMError):
    code = "llm_api_error"


class LLMBadResponseError(LLMError):
    code = "llm_bad_response"


@dataclass(frozen=True)
class InvoiceExtractionResult:
    invoice: InvoiceData
    usage: Usage
    model: str


class LLMClient(Protocol):
    """Anything that can extract invoice fields and classify documents."""

    def extract_invoice(self, text: str) -> InvoiceExtractionResult: ...

    def classify(self, text: str) -> Classification: ...
