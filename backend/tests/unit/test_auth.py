"""Actor immutability, session integrity and required auth configuration."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.security import SessionStore, verify_password
from app.core.config import AuthSettings
from app.security.authorization import ActorContext


def test_actor_cannot_be_mutated():
    actor = ActorContext(uuid4(), uuid4(), "employee")
    for field, value in (("company_id", uuid4()), ("role", "hr"), ("user_id", uuid4())):
        with pytest.raises(FrozenInstanceError):
            setattr(actor, field, value)
    with pytest.raises(ValueError):
        ActorContext(uuid4(), uuid4(), "admin")


def test_sessions_expire_and_restart_invalidates_them():
    now = [100.0]
    store = SessionStore("unit-test-secret" * 4, 60, clock=lambda: now[0])
    token, session = store.create(uuid4(), uuid4())
    assert store.resolve(token) == session
    assert SessionStore("unit-test-secret" * 4, 60).resolve(token) is None
    now[0] = 160.0
    assert store.resolve(token) is None


def test_session_revocation_and_randomness():
    store = SessionStore("unit-test-secret" * 4, 60)
    user, company = uuid4(), uuid4()
    first, first_session = store.create(user, company)
    second, second_session = store.create(user, company)
    assert first != second and first_session.csrf_token != second_session.csrf_token
    assert str(user) not in first and str(company) not in first
    store.revoke(first)
    assert store.resolve(first) is None
    assert store.resolve(second) == second_session


@pytest.mark.parametrize("token", ["a.é", "é.a", "..", "", "x" * 300])
def test_untrusted_cookie_text_is_rejected_without_errors(token):
    assert SessionStore("unit-test-secret" * 4, 60).resolve(token) is None


@pytest.mark.parametrize("hash_value", [None, "not-an-argon-hash"])
def test_invalid_password_hash_fails_closed(hash_value):
    assert not verify_password(hash_value, "unit-test-password")


def test_auth_secret_is_required_and_long_enough(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ValidationError):
        AuthSettings()
    with pytest.raises(ValidationError):
        AuthSettings(session_secret="short")
    assert AuthSettings(session_secret="a" * 64).session_cookie_secure


@pytest.mark.parametrize(
    "origin",
    [
        "https://host/path",
        "https://host/?x=1",
        "https://name@host",
        "https://host/#fragment",
    ],
)
def test_origin_cannot_include_paths_or_credentials(origin):
    with pytest.raises(ValidationError):
        AuthSettings(session_secret="a" * 64, app_origin=origin)
