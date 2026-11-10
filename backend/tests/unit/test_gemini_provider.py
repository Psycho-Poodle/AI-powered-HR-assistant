"""Official Google SDK over mock HTTP; no external credentials or API egress."""

import asyncio
import json

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import SecretStr

from app.agent.errors import LLMFailure
from app.agent.gemini_llm import GeminiLLM
from app.agent.providers import provider_factory
from app.core.config import LLMSettings


def settings(**changes):
    return LLMSettings(
        llm_provider="gemini",
        gemini_api_key=SecretStr("UNIT_TEST_KEY_NOT_REAL"),
        gemini_max_retries=changes.pop("gemini_max_retries", 0),
        **changes,
    )


def response(text="Hello", finish="STOP"):
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": finish,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "thoughtsTokenCount": 2,
        },
    }


def sdk(handler):
    return genai.Client(
        api_key="UNIT_TEST_KEY_NOT_REAL",
        enterprise=False,
        http_options=types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def test_selection_requires_gemini_key_without_openai_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "UNIT_TEST_OTHER_PROVIDER_KEY")
    factory = provider_factory(LLMSettings(llm_provider="gemini"))
    assert factory.provider == "gemini" and factory.model == "gemini-3.6-flash"
    with pytest.raises(LLMFailure, match="provider_missing_key"):
        factory()
    assert "UNIT_TEST_KEY_NOT_REAL" not in repr(settings())


def test_real_google_sdk_plan_compose_schema_context_and_usage():
    calls = []
    plan = {
        "intents": ["leave_balance"],
        "leave_evidence": None,
        "steps": [
            {
                "id": "balance",
                "tool": "get_leave_balance",
                "depends_on": [],
                "query": None,
                "start_date": None,
                "end_date": None,
                "message": None,
            }
        ],
    }

    def handler(request):
        calls.append(json.loads(request.content))
        assert "gemini-3.6-flash:generateContent" in str(request.url)
        return httpx.Response(
            200,
            json=response(json.dumps(plan) if len(calls) == 1 else "You have 12 days."),
        )

    async def scenario():
        llm = GeminiLLM(settings(), client=sdk(handler))
        try:
            assert (await llm.plan("my balance")).steps[0].tool == "get_leave_balance"
            assert await llm.compose("my balance", ()) == "You have 12 days."
            assert llm.usage == {"calls": 2, "input_tokens": 20, "output_tokens": 14}
        finally:
            await llm.aclose()

    asyncio.run(scenario())
    assert calls[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in calls[0]["generationConfig"]
    assert all(not c.get("tools") for c in calls)
    assert calls[0]["generationConfig"]["maxOutputTokens"] == 4096


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "provider_invalid_request"),
        (401, "provider_auth"),
        (403, "provider_model_access"),
        (404, "provider_model_access"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_errors_sanitized_and_never_fall_back(status, code):
    def handler(request):
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "PRIVATE_PROVIDER_DETAIL"}},
        )

    async def scenario():
        llm = GeminiLLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure) as error:
                await llm.plan("hello")
            assert str(error.value) == code
        finally:
            await llm.aclose()

    asyncio.run(scenario())


def test_retry_is_bounded_and_recovers_transient_failure():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(
                503, json={"error": {"code": 503, "message": "transient"}}
            )
        return httpx.Response(200, json=response())

    async def scenario():
        llm = GeminiLLM(settings(gemini_max_retries=2), client=sdk(handler))
        try:
            assert await llm.compose("hello", ()) == "Hello"
            assert len(calls) == 3 and llm.usage["calls"] == 1
        finally:
            await llm.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text,finish",
    [
        ("not JSON", "STOP"),
        ("{}", "MAX_TOKENS"),
        (
            json.dumps(
                {
                    "intents": ["leave_confirmation"],
                    "leave_evidence": None,
                    "steps": [
                        {
                            "id": "write",
                            "tool": "confirm_leave",
                            "depends_on": [],
                            "query": None,
                            "start_date": None,
                            "end_date": None,
                            "message": None,
                        }
                    ],
                }
            ),
            "STOP",
        ),
    ],
)
def test_invalid_truncated_and_mutation_plans_fail_closed(text, finish):
    async def scenario():
        llm = GeminiLLM(
            settings(),
            client=sdk(
                lambda request: httpx.Response(200, json=response(text, finish))
            ),
        )
        try:
            with pytest.raises(LLMFailure, match="provider_invalid_response"):
                await llm.plan("hello")
        finally:
            await llm.aclose()

    asyncio.run(scenario())


def test_transport_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("PRIVATE_TIMEOUT", request=request)

    async def scenario():
        llm = GeminiLLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure, match="provider_timeout"):
                await llm.compose("hello", ())
        finally:
            await llm.aclose()

    asyncio.run(scenario())
