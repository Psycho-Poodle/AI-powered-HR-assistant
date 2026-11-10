"""Opt-in paid SDK smoke; never used by the automated/offline test drivers."""

import asyncio
import json
from pathlib import Path

from app.agent.errors import LLMFailure
from app.agent.providers import provider_factory
from app.core.config import LLMSettings


async def main():
    # Only this explicitly invoked diagnostic reads the local dotenv file.
    settings = LLMSettings(
        _env_file=Path(__file__).resolve().parents[1] / ".env",
    )
    llm = None
    try:
        if settings.llm_provider == "fake":
            raise LLMFailure("live_provider_required")
        llm = provider_factory(settings)()
        plan = await llm.plan("Hello. Greet me; do not access any HR records.")
        if any(s.tool != "talk" for s in plan.steps):
            raise LLMFailure("unexpected_smoke_plan")
        await llm.compose("Hello. Greet me without making any HR factual claims.", ())
        print(
            json.dumps(
                {
                    "provider": llm.provider,
                    "model": llm.model,
                    "usage": llm.usage,
                    "sdk_smoke": "passed",
                }
            )
        )
        return 0
    except LLMFailure as error:
        print(json.dumps({"sdk_smoke": "not_passed", "code": error.code}))
        return 1
    finally:
        if llm is not None:
            await llm.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
