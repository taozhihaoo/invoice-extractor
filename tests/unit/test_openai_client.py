"""OpenAI client tests using a fake SDK - no network, no real waiting."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)

from src.llm.base import (
    LLMAuthError,
    LLMBadResponseError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from src.llm.openai_client import OpenAIClient

BASE_URL = "https://api.openai.com/v1/chat/completions"

GOOD_INVOICE_PAYLOAD = {
    "supplier": "OpenAI Test GmbH",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-09-30",
    "due_date": "2026-10-31",
    "subtotal": 100.0,
    "tax": 20.0,
    "total": 120.0,
    "currency": "EUR",
}


def api_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=17),
    )


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes, max_retries=2, max_chars=12_000) -> tuple[OpenAIClient, FakeCompletions]:
    completions = FakeCompletions(outcomes)
    client = OpenAIClient(
        api_key="test-key-not-real",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        max_retries=max_retries,
        max_chars=max_chars,
        sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        sleeper=lambda seconds: None,
    )
    return client, completions


def rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else None
    return RateLimitError(
        "rate limited",
        response=httpx.Response(429, headers=headers, request=httpx.Request("POST", BASE_URL)),
        body=None,
    )


def auth_error() -> AuthenticationError:
    return AuthenticationError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("POST", BASE_URL)),
        body=None,
    )


def timeout_error() -> APITimeoutError:
    return APITimeoutError(httpx.Request("POST", BASE_URL))


def server_error() -> InternalServerError:
    return InternalServerError(
        "boom",
        response=httpx.Response(500, request=httpx.Request("POST", BASE_URL)),
        body=None,
    )


class TestSuccessfulExtraction:
    def test_parses_invoice_and_usage(self):
        client, completions = make_client([api_response(GOOD_INVOICE_PAYLOAD)])
        result = client.extract_invoice("invoice text")
        assert result.invoice.supplier == "OpenAI Test GmbH"
        assert result.invoice.total == 120.0
        assert result.usage.prompt_tokens == 42
        assert result.usage.completion_tokens == 17
        assert result.model == "gpt-4o-mini"

    def test_request_uses_strict_schema_and_zero_temperature(self):
        client, completions = make_client([api_response(GOOD_INVOICE_PAYLOAD)])
        client.extract_invoice("invoice text")
        kwargs = completions.calls[0]
        assert kwargs["temperature"] == 0
        schema = kwargs["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert set(schema["schema"]["required"]) == {
            "supplier", "invoice_number", "invoice_date", "due_date",
            "subtotal", "tax", "total", "currency",
        }

    def test_long_text_is_truncated_before_sending(self):
        client, completions = make_client([api_response(GOOD_INVOICE_PAYLOAD)], max_chars=50)
        client.extract_invoice("x" * 5000)
        user_content = completions.calls[0]["messages"][1]["content"]
        assert len(user_content) == 50


class TestRetries:
    def test_rate_limit_then_success(self):
        client, completions = make_client(
            [rate_limit_error(), api_response(GOOD_INVOICE_PAYLOAD)]
        )
        result = client.extract_invoice("invoice text")
        assert result.invoice.supplier == "OpenAI Test GmbH"
        assert len(completions.calls) == 2

    def test_rate_limit_exhausted_raises(self):
        client, completions = make_client(
            [rate_limit_error(), rate_limit_error(), rate_limit_error()], max_retries=2
        )
        with pytest.raises(LLMRateLimitError):
            client.extract_invoice("invoice text")
        assert len(completions.calls) == 3  # initial + 2 retries

    def test_retry_after_header_is_honoured(self):
        sleeps: list[float] = []
        completions = FakeCompletions([rate_limit_error("3"), api_response(GOOD_INVOICE_PAYLOAD)])
        client = OpenAIClient(
            api_key="k", model="m", timeout_seconds=1, max_retries=2,
            sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
            sleeper=sleeps.append,
        )
        client.extract_invoice("invoice text")
        assert sleeps == [3.0]

    def test_timeout_retries_then_raises(self):
        client, completions = make_client(
            [timeout_error(), timeout_error(), timeout_error()], max_retries=1
        )
        with pytest.raises(LLMTimeoutError):
            client.extract_invoice("invoice text")
        assert len(completions.calls) == 2

    def test_server_error_retries_then_succeeds(self):
        client, completions = make_client([server_error(), api_response(GOOD_INVOICE_PAYLOAD)])
        result = client.extract_invoice("invoice text")
        assert result.invoice.supplier == "OpenAI Test GmbH"
        assert len(completions.calls) == 2

    def test_auth_error_fails_fast_without_retry(self):
        client, completions = make_client([auth_error(), auth_error()])
        with pytest.raises(LLMAuthError):
            client.extract_invoice("invoice text")
        assert len(completions.calls) == 1


class TestBadResponses:
    def test_malformed_json_raises_bad_response(self):
        broken = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json {"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        client, _ = make_client([broken])
        with pytest.raises(LLMBadResponseError):
            client.extract_invoice("invoice text")

    def test_schema_violation_negative_amount_raises_bad_response(self):
        payload = dict(GOOD_INVOICE_PAYLOAD, total=-5)
        client, _ = make_client([api_response(payload)])
        with pytest.raises(LLMBadResponseError):
            client.extract_invoice("invoice text")


class TestClassification:
    def test_classify_returns_model_confidence(self):
        client, _ = make_client(
            [api_response({"document_type": "receipt", "confidence": 0.91})]
        )
        result = client.classify("some text")
        assert result.document_type.value == "receipt"
        assert result.confidence == 0.91
        assert result.method == "llm"


class TestErrorHierarchy:
    def test_all_llm_errors_share_base(self):
        for cls in (LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMBadResponseError):
            assert issubclass(cls, LLMError)
