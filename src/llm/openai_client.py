"""OpenAI implementation of :class:`LLMClient` using structured outputs.

Design notes:
- strict JSON schema (``response_format``) so the model cannot add keys;
- explicit retry policy: rate limits (honouring ``Retry-After``), timeouts and
  transient 5xx are retried with exponential backoff; auth errors fail fast;
- SDK exceptions are translated into the LLMError hierarchy so callers never
  import the openai package;
- token usage is captured and returned for every call;
- ``sdk_client`` and ``sleeper`` are injectable so tests run fully offline and
  never actually wait.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from ..models import Classification, DocumentType, InvoiceData, Usage
from .base import (
    InvoiceExtractionResult,
    LLMAPIError,
    LLMAuthError,
    LLMBadResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .schemas import (
    CLASSIFICATION_JSON_SCHEMA,
    INVOICE_JSON_SCHEMA,
    SYSTEM_CLASSIFY_PROMPT,
    SYSTEM_EXTRACT_PROMPT,
)

_MAX_BACKOFF_SECONDS = 8.0


class OpenAIClient:
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str | None = None,
        max_chars: int = 12_000,
        sdk_client: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._max_chars = max_chars
        self._sleep = sleeper
        self._client = sdk_client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # retries are handled explicitly below
        )

    # LLMClient protocol ---------------------------------------------------

    def extract_invoice(self, text: str) -> InvoiceExtractionResult:
        content, usage = self._complete(
            INVOICE_JSON_SCHEMA, SYSTEM_EXTRACT_PROMPT, text[: self._max_chars]
        )
        try:
            invoice = InvoiceData.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMBadResponseError(
                f"model returned data that violates the invoice schema: {exc}"
            ) from exc
        return InvoiceExtractionResult(invoice=invoice, usage=usage, model=self._model)

    def classify(self, text: str) -> Classification:
        content, _ = self._complete(
            CLASSIFICATION_JSON_SCHEMA, SYSTEM_CLASSIFY_PROMPT, text[: self._max_chars]
        )
        try:
            data = json.loads(content)
            document_type = DocumentType(data["document_type"])
            confidence = float(data["confidence"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise LLMBadResponseError(
                f"model returned an invalid classification payload: {exc}"
            ) from exc
        if not 0.0 <= confidence <= 1.0:
            raise LLMBadResponseError("classification confidence out of range")
        return Classification(
            document_type=document_type, confidence=confidence, method="llm"
        )

    # internals ------------------------------------------------------------

    def _complete(
        self, schema: dict[str, Any], system_prompt: str, user_text: str
    ) -> tuple[str, Usage]:
        attempt = 0
        while True:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text},
                    ],
                    response_format={"type": "json_schema", "json_schema": schema},
                    temperature=0,
                )
            except AuthenticationError as exc:
                raise LLMAuthError(
                    "OpenAI authentication failed; check OPENAI_API_KEY"
                ) from exc
            except RateLimitError as exc:
                if attempt >= self._max_retries:
                    raise LLMRateLimitError(
                        "OpenAI rate limit exceeded; retries exhausted"
                    ) from exc
                self._sleep(self._backoff(attempt, _retry_after_seconds(exc)))
                attempt += 1
            except APITimeoutError as exc:
                if attempt >= self._max_retries:
                    raise LLMTimeoutError(
                        "OpenAI request timed out; retries exhausted"
                    ) from exc
                self._sleep(self._backoff(attempt))
                attempt += 1
            except APIConnectionError as exc:
                if attempt >= self._max_retries:
                    raise LLMAPIError(
                        "could not connect to the OpenAI API; retries exhausted"
                    ) from exc
                self._sleep(self._backoff(attempt))
                attempt += 1
            except APIStatusError as exc:
                status = getattr(exc, "status_code", 0) or 0
                if 500 <= status < 600 and attempt < self._max_retries:
                    self._sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise LLMAPIError(f"OpenAI API error (HTTP {status})") from exc
            else:
                break

        raw_usage = getattr(response, "usage", None)
        usage = Usage(
            prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
        )
        content = response.choices[0].message.content or ""
        return content, usage

    def _backoff(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, 60.0)
        return min(_MAX_BACKOFF_SECONDS, 0.5 * (2**attempt))


def _retry_after_seconds(exc: RateLimitError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
