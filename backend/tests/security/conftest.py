"""Real PostgreSQL HTTP tests; only the connection lifetime is overridden."""

import os
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth.dependencies import get_db
from app.core.config import AuthSettings, Settings, get_auth_settings


@pytest.fixture
def client(seeded, monkeypatch):
    settings = AuthSettings(
        session_secret=secrets.token_hex(32),
        app_origin="https://testserver",
        session_cookie_secure=True,
    )
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(database_url=os.environ["TEST_DATABASE_URL"]),
    )
    monkeypatch.setattr(main, "get_auth_settings", lambda: settings)
    app = main.create_app()

    def connection():
        yield seeded

    app.dependency_overrides[get_db] = connection
    app.dependency_overrides[get_auth_settings] = lambda: settings
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as test_client:
        yield test_client
