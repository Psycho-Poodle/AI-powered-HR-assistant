"""Database configuration loaded at startup, never at import time."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    task_runner_enabled: bool = True
    database_url: PostgresDsn

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme not in {"postgres", "postgresql"}:
            raise ValueError("Use a PostgreSQL URL supported by psycopg")
        if not value.path or value.path == "/":
            raise ValueError("An explicit database name is required")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    # Safe host default; Compose explicitly selects Gemini for the live demo.
    llm_provider: Literal["fake", "openai", "gemini"] = "fake"
    gemini_model: str = Field(default="gemini-3.6-flash", min_length=1, max_length=100)
    gemini_api_key: SecretStr | None = None
    gemini_timeout_seconds: float = Field(default=30, ge=1, le=120)
    gemini_max_retries: int = Field(default=2, ge=0, le=3)
    gemini_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    openai_model: str = Field(default="gpt-5.4-mini", min_length=1, max_length=100)
    openai_api_key: SecretStr | None = None
    openai_timeout_seconds: float = Field(default=30, ge=1, le=120)
    openai_max_retries: int = Field(default=2, ge=0, le=3)
    openai_max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    llm_max_context_chars: int = Field(default=24000, ge=4000, le=64000)
    llm_max_calls_per_task: int = Field(default=12, ge=2, le=64)


def get_llm_settings() -> LLMSettings:
    return LLMSettings()


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    session_secret: SecretStr = Field(min_length=32)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    session_cookie_secure: bool = True
    app_origin: HttpUrl = HttpUrl("http://localhost:8000")

    @field_validator("app_origin")
    @classmethod
    def validate_origin(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.path not in (None, "/")
            or value.query
            or value.fragment
            or value.username
        ):
            raise ValueError("APP_ORIGIN must contain only scheme, host and port")
        return value


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
