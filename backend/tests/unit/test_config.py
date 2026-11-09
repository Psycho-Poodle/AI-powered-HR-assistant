"""Reject missing or non-PostgreSQL connection configuration."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///local.db",
        "https://localhost/db",
        "garbage",
        "postgresql://localhost",
        "postgresql+asyncpg://localhost/hr",
    ],
)
def test_invalid_database_url(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=url)


def test_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/hr")
    assert Settings().database_url.path == "/hr"


def test_database_url_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()
