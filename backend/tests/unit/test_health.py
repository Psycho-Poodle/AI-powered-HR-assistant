"""Exercise the public liveness contract through the ASGI application."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch, raises

from app import main
from app.core.config import AuthSettings, Settings


def test_health_live(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "get_auth_settings",
        lambda: AuthSettings(session_secret="unit-test-secret-" * 4),
    )
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            task_runner_enabled=False,
            database_url="postgresql://unit:unit@localhost/unit",
        ),
    )
    monkeypatch.setattr(main, "check_database", lambda url: "unit-test-stub")
    with TestClient(main.app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_startup_fails_when_database_probe_fails(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            task_runner_enabled=False,
            database_url="postgresql://unit:unit@localhost/unit",
        ),
    )

    def fail_probe(url: str) -> str:
        raise RuntimeError("Required PostgreSQL vector extension is missing")

    monkeypatch.setattr(main, "check_database", fail_probe)
    with (
        raises(RuntimeError, match="vector extension is missing"),
        TestClient(main.app),
    ):
        pass
