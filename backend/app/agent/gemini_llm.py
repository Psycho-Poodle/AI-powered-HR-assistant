"""Official Google Gen AI async adapter; shares the authorized read-only contract."""

import asyncio

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.agent.errors import LLMFailure
from app.agent.live_llm import (
    COMPOSE_INSTRUCTIONS,
    PLAN_INSTRUCTIONS,
    LiveLLM,
    ModelPlan,
)


class GeminiLLM(LiveLLM):
    provider = "gemini"

    def __init__(self, settings, client=None):
        if (
            not settings.gemini_api_key
            or not settings.gemini_api_key.get_secret_value().strip()
        ):
            raise LLMFailure("provider_missing_key")
        super().__init__(settings, settings.gemini_model)
        self.client = client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            enterprise=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com",
                api_version="v1beta",
                timeout=int(settings.gemini_timeout_seconds * 1000),
                # Retries are bounded explicitly below; never multiply SDK retries.
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=httpx.AsyncClient(
                    timeout=settings.gemini_timeout_seconds
                ),
            ),
        )

    async def _generate(self, original, instructions, results=None, schema=None):
        if self.usage["calls"] >= self.settings.llm_max_calls_per_task:
            raise LLMFailure("provider_budget_exceeded")
        content = self._input(original, results)[0]["content"]
        self.usage["calls"] += 1
        config = types.GenerateContentConfig(
            system_instruction=instructions,
            max_output_tokens=self.settings.gemini_max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            response_mime_type="application/json" if schema else "text/plain",
            response_json_schema=schema.model_json_schema() if schema else None,
        )
        for attempt in range(self.settings.gemini_max_retries + 1):
            try:
                async with asyncio.timeout(self.settings.gemini_timeout_seconds):
                    response = await self.client.aio.models.generate_content(
                        model=self.model, contents=content, config=config
                    )
                usage = response.usage_metadata
                self.usage["input_tokens"] += (
                    getattr(usage, "prompt_token_count", 0) or 0
                )
                self.usage["output_tokens"] += (
                    getattr(usage, "candidates_token_count", 0) or 0
                ) + (getattr(usage, "thoughts_token_count", 0) or 0)
                if (
                    not response.candidates
                    or any(
                        c.finish_reason != types.FinishReason.STOP
                        for c in response.candidates
                    )
                    or any(
                        c.content
                        and any(p.function_call for p in (c.content.parts or ()))
                        for c in response.candidates
                    )
                ):
                    raise LLMFailure("provider_invalid_response")
                if not response.text or len(response.text) > 20000:
                    raise LLMFailure("provider_invalid_response")
                return response
            except (TimeoutError, httpx.TimeoutException):
                code = "provider_timeout"
            except httpx.TransportError:
                code = "provider_unavailable"
            except errors.APIError as error:
                code = {
                    400: "provider_invalid_request",
                    401: "provider_auth",
                    403: "provider_model_access",
                    404: "provider_model_access",
                    429: "provider_rate_limited",
                }.get(error.code, "provider_unavailable")
                if error.code not in {429, 500, 502, 503, 504}:
                    raise LLMFailure(code) from None
            except (ValidationError, ValueError):
                raise LLMFailure("provider_invalid_response") from None
            if attempt == self.settings.gemini_max_retries:
                raise LLMFailure(code) from None
            await asyncio.sleep(0.5 * (2**attempt))

    async def plan(self, original_request):
        response = await self._generate(
            original_request, PLAN_INSTRUCTIONS, schema=ModelPlan
        )
        try:
            return ModelPlan.model_validate_json(response.text).validated_plan()
        except (ValueError, ValidationError):
            raise LLMFailure("provider_invalid_response") from None

    async def compose(self, original_request, subtasks):
        response = await self._generate(
            original_request, COMPOSE_INSTRUCTIONS, results=subtasks
        )
        return response.text

    async def aclose(self):
        await self.client.aio.aclose()
        self.client.close()
