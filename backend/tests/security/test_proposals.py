"""Confirm/cancel are authenticated owner actions, not LLM tools."""

import os
import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app import main
from app.agent.state import Plan
from app.api.leave import get_mutation_engine
from app.auth.dependencies import get_db
from app.core.config import AuthSettings, Settings, get_auth_settings
from app.db.models import ActionProposal, LeaveBalance, LeaveRequest
from app.seed.load_seed import seed_id

pytestmark = pytest.mark.integration


@pytest.fixture
def proposal_client(booking_engine, monkeypatch):
    settings = AuthSettings(
        session_secret=secrets.token_hex(32), app_origin="https://testserver"
    )
    monkeypatch.setattr(main, "get_auth_settings", lambda: settings)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(database_url=os.environ["TEST_DATABASE_URL"]),
    )
    app = main.create_app()

    def db():
        with booking_engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_mutation_engine] = lambda: booking_engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as client:
        yield client


def login(client, user="maya"):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": "ephemeral-test-password"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def make(client):
    headers = login(client)
    response = client.post(
        "/api/v1/leave/proposals",
        json={
            "task_id": str(seed_id("proposal-test-task", "maya")),
            "start_date": "2026-11-09",
            "end_date": "2026-11-11",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json(), headers


def test_http_confirm_commits_once_and_duplicate_is_conflict(
    proposal_client, booking_engine
):
    proposal, headers = make(proposal_client)
    identifier = proposal["id"]
    assert proposal["calendar"] == "fictional-mon-fri-v1"
    assert proposal_client.get("/api/v1/leave/balance").json()["days_left"] == "12.00"
    response = proposal_client.post(
        f"/api/v1/leave/proposals/{identifier}/confirm",
        json={"expected_version": 1},
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["remaining_days"] == "9.00"
    assert (
        proposal_client.post(
            f"/api/v1/leave/proposals/{identifier}/confirm",
            json={"expected_version": 1},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        proposal_client.get(f"/api/v1/leave/proposals/{identifier}").json()["status"]
        == "confirmed"
    )
    with booking_engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(LeaveRequest)).scalar()
            == 1
        )
        assert (
            connection.execute(
                select(LeaveBalance.days_left).where(
                    LeaveBalance.user_id == seed_id("user", "summit", "maya")
                )
            ).scalar()
            == 9
        )


@pytest.mark.parametrize("person", ["ravi", "leila"])
def test_other_tenant_or_same_tenant_hr_cannot_access_proposal(proposal_client, person):
    proposal, _ = make(proposal_client)
    headers = login(proposal_client, person)
    path = f"/api/v1/leave/proposals/{proposal['id']}"
    assert proposal_client.get(path).status_code == 404
    for action in ("confirm", "cancel"):
        assert (
            proposal_client.post(
                path + "/" + action, json={"expected_version": 1}, headers=headers
            ).status_code
            == 404
        )


def test_csrf_and_origin_are_required_for_confirmation(proposal_client):
    proposal, headers = make(proposal_client)
    path = f"/api/v1/leave/proposals/{proposal['id']}/confirm"
    assert proposal_client.post(path, json={"expected_version": 1}).status_code == 403
    assert (
        proposal_client.post(
            path,
            json={"expected_version": 1},
            headers=headers | {"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert proposal_client.get("/api/v1/leave/balance").json()["days_left"] == "12.00"


@pytest.mark.parametrize(
    "extra",
    [{"role": "hr"}, {"company_id": "pebble"}, {"user_id": "maya"}, {"approved": True}],
)
def test_confirm_rejects_forged_identity_and_approval_fields(proposal_client, extra):
    proposal, headers = make(proposal_client)
    assert (
        proposal_client.post(
            f"/api/v1/leave/proposals/{proposal['id']}/confirm",
            json={"expected_version": 1, **extra},
            headers=headers,
        ).status_code
        == 422
    )


def test_http_expiry_transition_is_committed_despite_409(
    proposal_client, booking_engine
):
    proposal, headers = make(proposal_client)
    with booking_engine.begin() as connection:
        from datetime import timedelta
        from uuid import UUID

        connection.execute(
            update(ActionProposal)
            .where(ActionProposal.id == UUID(proposal["id"]))
            .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    response = proposal_client.post(
        f"/api/v1/leave/proposals/{proposal['id']}/confirm",
        json={"expected_version": 1},
        headers=headers,
    )
    assert (
        response.status_code == 409 and response.json()["error"]["message"] == "expired"
    )
    state = proposal_client.get(f"/api/v1/leave/proposals/{proposal['id']}").json()
    assert state["status"] == "expired" and state["version"] == 2


def test_http_cancel_never_books_or_debits(proposal_client):
    proposal, headers = make(proposal_client)
    response = proposal_client.post(
        f"/api/v1/leave/proposals/{proposal['id']}/cancel",
        json={"expected_version": 1},
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert proposal_client.get("/api/v1/leave/balance").json()["days_left"] == "12.00"


@pytest.mark.parametrize(
    "tool", ["confirm_proposal", "confirm_leave", "execute_sql", "cancel_proposal"]
)
def test_llm_plan_cannot_select_confirmation_or_cancellation(tool):
    with pytest.raises(ValidationError):
        Plan.model_validate(
            {"steps": [{"id": "write", "tool": tool, "args": {"expected_version": 1}}]}
        )
