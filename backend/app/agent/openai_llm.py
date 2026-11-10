"""Official asynchronous Responses API adapter; no executable model tool calls."""

import asyncio

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)
from pydantic import ValidationError

from app.agent.errors import LLMFailure
from app.agent.live_llm import (
    COMPOSE_INSTRUCTIONS,
    PLAN_INSTRUCTIONS,
    LiveLLM,
    ModelPlan,
)


class OpenAILLM(LiveLLM):
    provider = "openai"
    replans_with_context = True

    def __init__(self, settings, client=None):
        if (
            not settings.openai_api_key
            or not settings.openai_api_key.get_secret_value().strip()
        ):
            raise LLMFailure("provider_missing_key")
        super().__init__(settings, settings.openai_model)
        self.client = client or AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    async def _call(self, operation, **kwargs):
        if self.usage["calls"] >= self.settings.llm_max_calls_per_task:
            raise LLMFailure("provider_budget_exceeded")
        self.usage["calls"] += 1
        try:
            # Overall deadline also bounds SDK retry/backoff time.
            async with asyncio.timeout(
                self.settings.openai_timeout_seconds
                * (self.settings.openai_max_retries + 1)
                + 5
            ):
                response = await operation(
                    model=self.model,
                    store=False,
                    max_output_tokens=self.settings.openai_max_output_tokens,
                    reasoning={"effort": "low"},
                    **kwargs,
                )
            if getattr(response, "status", None) != "completed":
                raise LLMFailure("provider_invalid_response")
            usage = getattr(response, "usage", None)
            self.usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
            return response
        except (TimeoutError, APITimeoutError):
            raise LLMFailure("provider_timeout") from None
        except APIConnectionError:
            raise LLMFailure("provider_unavailable") from None
        except APIStatusError as error:
            body = error.body if isinstance(error.body, dict) else {}
            body = body.get("error", body)
            if not isinstance(body, dict):
                body = {}
            if error.status_code == 429 and (
                body.get("type") == "insufficient_quota"
                or body.get("code")
                in {
                    "insufficient_quota",
                    "credit_balance_exhausted",
                    "billing_hard_limit_reached",
                    "organization_usage_limit_exceeded",
                    "project_usage_limit_exceeded",
                }
            ):
                raise LLMFailure("provider_quota_exhausted") from None
            code = {
                401: "provider_auth",
                403: "provider_model_access",
                404: "provider_model_access",
                429: "provider_rate_limited",
            }.get(error.status_code, "provider_unavailable")
            raise LLMFailure(code) from None
        except (ValidationError, ValueError):
            raise LLMFailure("provider_invalid_response") from None
        except OpenAIError:
            raise LLMFailure("provider_invalid_response") from None

    async def plan(self, original_request):
        response = await self._call(
            self.client.responses.parse,
            instructions=PLAN_INSTRUCTIONS,
            input=self._input(original_request),
            text_format=ModelPlan,
        )
        if response.output_parsed is None:
            raise LLMFailure("provider_invalid_response")
        try:
            return ModelPlan.model_validate(response.output_parsed).validated_plan()
        except (ValueError, ValidationError):
            raise LLMFailure("provider_invalid_response") from None

    async def compose(self, original_request, subtasks):
        response = await self._call(
            self.client.responses.create,
            instructions=COMPOSE_INSTRUCTIONS,
            input=self._input(original_request, subtasks),
        )
        if not response.output_text or len(response.output_text) > 20000:
            raise LLMFailure("provider_invalid_response")
        return response.output_text

    async def aclose(self):
        await self.client.close()
