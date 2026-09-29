"""LLM provider abstraction.

Business logic depends only on the ``LLMClient`` protocol; concrete
implementations (OpenAI, deterministic mock) are injected at composition
time. Provider SDK exceptions never leak past this layer.
"""

from .base import (
    InvoiceExtractionResult,
    LLMAPIError,
    LLMAuthError,
    LLMBadResponseError,
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .mock import MockLLMClient
from .openai_client import OpenAIClient

__all__ = [
    "InvoiceExtractionResult",
    "LLMAPIError",
    "LLMAuthError",
    "LLMBadResponseError",
    "LLMClient",
    "LLMError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "MockLLMClient",
    "OpenAIClient",
]
