"""Explicit provider selection. No failure path substitutes a fake provider."""

from app.agent.fake_llm import FakeLLM
from app.core.config import get_llm_settings


def provider_factory(settings=None):
    settings = settings or get_llm_settings()
    if settings.llm_provider == "fake":
        return FakeLLM
    if settings.llm_provider == "gemini":
        from app.agent.gemini_llm import GeminiLLM

        def factory():
            return GeminiLLM(settings)

        factory.provider, factory.model = "gemini", settings.gemini_model
        return factory
    from app.agent.openai_llm import OpenAILLM

    def factory():
        return OpenAILLM(settings)

    factory.provider, factory.model = "openai", settings.openai_model
    return factory
