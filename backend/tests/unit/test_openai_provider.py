"""Official SDK request/response contract over MockTransport; no external calls."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.agent.errors import LLMFailure
from app.agent.fake_llm import FakeLLM
from app.agent.openai_llm import OpenAILLM
from app.agent.providers import provider_factory
from app.core.config import LLMSettings


def settings(**changes):
    return LLMSettings(
        llm_provider="openai",
        openai_api_key=SecretStr("UNIT_TEST_KEY_NOT_REAL"),
        openai_max_retries=0,
        **changes,
    )


def operation(tool="get_leave_balance", **changes):
    return {
        "id": "balance",
        "tool": tool,
        "depends_on": [],
        "query": None,
        "start_date": None,
        "end_date": None,
        "message": None,
        **changes,
    }


def response(text, status="completed"):
    return {
        "id": "resp_unit",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-5.4-mini",
        "output": [
            {
                "id": "msg_unit",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def sdk(handler):
    return AsyncOpenAI(
        api_key="UNIT_TEST_KEY_NOT_REAL",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_explicit_selection_and_missing_key(monkeypatch):
    assert provider_factory(LLMSettings()) is FakeLLM
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMFailure, match="provider_missing_key"):
        provider_factory(LLMSettings(llm_provider="openai"))()
    assert "UNIT_TEST_KEY_NOT_REAL" not in repr(settings())


def test_official_responses_parse_and_composition_are_async_and_bounded():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            text = json.dumps(
                {
                    "steps": [operation()],
                    "intents": ["leave_balance"],
                    "leave_evidence": None,
                }
            )
        else:
            text = "You have 12 days of leave."
        return httpx.Response(200, json=response(text))

    async def scenario():
        llm = OpenAILLM(settings(), client=sdk(handler))
        try:
            plan = await llm.plan("How many leave days do I have?")
            assert plan.steps[0].tool == "get_leave_balance"
            assert await llm.compose("hello", ()) == "You have 12 days of leave."
            assert llm.usage == {"calls": 2, "input_tokens": 20, "output_tokens": 10}
        finally:
            await llm.aclose()

    asyncio.run(scenario())
    assert all(c["model"] == "gpt-5.4-mini" and c["store"] is False for c in calls)
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    assert calls[0]["max_output_tokens"] == 2048
    assert all("tools" not in c for c in calls)  # No SDK-hosted mutation tools.


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_auth"),
        (403, "provider_model_access"),
        (404, "provider_model_access"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_provider_failure_is_sanitized_and_never_falls_back(status, code):
    def handler(request):
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "PRIVATE_PROVIDER_MESSAGE UNIT_TEST_KEY_NOT_REAL",
                    "type": "test",
                }
            },
        )

    async def scenario():
        llm = OpenAILLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure) as error:
                await llm.plan("hello")
            assert error.value.code == code
            assert "PRIVATE" not in str(error.value) and "UNIT_TEST" not in str(
                error.value
            )
        finally:
            await llm.aclose()

    asyncio.run(scenario())


def test_invalid_model_tool_is_rejected_without_dispatch():
    def handler(request):
        return httpx.Response(
            200,
            json=response(
                json.dumps(
                    {
                        "steps": [operation(tool="confirm_leave")],
                        "intents": ["leave_confirmation"],
                        "leave_evidence": None,
                    }
                )
            ),
        )

    async def scenario():
        llm = OpenAILLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure, match="provider_invalid_response"):
                await llm.plan("confirm leave")
        finally:
            await llm.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "code",
    [
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_usage_limit_exceeded",
    ],
)
def test_quota_errors_are_distinguished_from_temporary_rate_limits(code):
    def handler(request):
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "PRIVATE_PROVIDER_DETAIL",
                    "type": "insufficient_quota",
                    "code": code,
                }
            },
        )

    async def scenario():
        llm = OpenAILLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure, match="provider_quota_exhausted"):
                await llm.plan("my balance")
        finally:
            await llm.aclose()

    asyncio.run(scenario())


def test_context_and_call_budgets_fail_closed():
    from app.schemas.workflow import ConversationContext, Turn

    llm = OpenAILLM(
        settings(llm_max_context_chars=4000, llm_max_calls_per_task=2),
        client=sdk(lambda request: httpx.Response(200, json=response("hello"))),
    )
    llm.set_context(
        ConversationContext(
            history=(Turn(user="old" * 2000, assistant="answer" * 1000),)
        )
    )
    assert "oldold" not in json.dumps(llm._input("hello"))
    with pytest.raises(LLMFailure, match="provider_context_limit"):
        llm._input("x" * 5000)

    async def scenario():
        try:
            await llm.compose("hello", ())
            await llm.compose("hello", ())
            with pytest.raises(LLMFailure, match="provider_budget_exceeded"):
                await llm.compose("hello", ())
        finally:
            await llm.aclose()

    asyncio.run(scenario())


def test_test_transport_guard_blocks_real_openai_egress():
    async def scenario():
        async with httpx.AsyncClient() as client:
            with pytest.raises(AssertionError, match="forbidden"):
                await client.get("https://api.openai.com/v1/models")

    asyncio.run(scenario())


def test_timeout_is_sanitized_without_fake_fallback():
    def handler(request):
        raise httpx.ReadTimeout("PRIVATE_PROVIDER_DETAIL", request=request)

    async def scenario():
        llm = OpenAILLM(settings(), client=sdk(handler))
        try:
            with pytest.raises(LLMFailure, match="provider_timeout"):
                await llm.plan("hello")
            assert llm.usage["calls"] == 1
        finally:
            await llm.aclose()

    asyncio.run(scenario())
