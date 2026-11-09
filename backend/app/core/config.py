"""Database configuration loaded at startup, never at import time."""

from functools import lru_cache

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
