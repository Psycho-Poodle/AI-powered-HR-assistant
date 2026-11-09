"""Adversarial requests against real seeded SQL; no prompt-based access checks."""

import time
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends
from sqlalchemy import insert, select, text

from app.auth.dependencies import require_hr
from app.auth.security import COOKIE_NAME
from app.db.models import (
    ActionProposal,
    Company,
    Conversation,
    EmployeeProfile,
    LeaveHistory,
    LeaveRequest,
    Policy,
    Task,
    User,
)
from app.repositories.leave import get_balance, get_history, get_profile
from app.repositories.policies import get_policy
from app.security.authorization import ActorContext
from app.seed.load_seed import seed_id

pytestmark = pytest.mark.integration
PASSWORD = "ephemeral-test-password"


def sign_in(client, username="maya"):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


def policy_id(company, slug):
    return str(seed_id("policy", company, slug, "1"))


MATRIX = {
    "maya": [200, 404, 404, 200],
    "leila": [200, 404, 200, 200],
    "ravi": [404, 200, 404, 404],
}
SOURCES = [
    ("summit", "late-arrival"),
    ("pebble", "late-arrival"),
    ("summit", "ceo-salary-band"),
    ("summit", "poisoned-policy"),
]


@pytest.mark.parametrize("username,index", [(u, i) for u in MATRIX for i in range(4)])
def test_policy_permission_matrix(client, seeded, username, index):
    login = sign_in(client, username)
    company, slug = SOURCES[index]
    pid = policy_id(company, slug)
    response = client.get(f"/api/v1/policies/{pid}")
    expected = MATRIX[username][index]
    assert response.status_code == expected
    actor = ActorContext(
        seed_id("user", login["company"]["slug"], username),
        seed_id("company", login["company"]["slug"]),
        login["role"],
    )
    row = get_policy(seeded, actor, seed_id("policy", company, slug, "1"))
    if expected == 404:
        assert row is None  # Forbidden text never leaves the repository query.
        assert "body" not in response.text
    else:
        assert row is not None and response.json()["body"] == row["body"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "username,expected", [("maya", 404), ("leila", 200), ("ravi", 404)]
)
def test_hr_visibility_is_tenant_scoped(client, seeded, username, expected):
    pid = seeded.execute(
        insert(Policy)
        .values(
            company_id=seed_id("company", "summit"),
            slug="test-hr",
            title="Fictional HR",
            body="FICTIONAL DEMONSTRATION DATA",
            visibility="hr",
            version=1,
            status="published",
            source_filename="test",
            source_sha256="a" * 64,
            provenance="fictional_demo",
            is_demo=True,
        )
        .returning(Policy.id)
    ).scalar_one()
    sign_in(client, username)
    assert client.get(f"/api/v1/policies/{pid}").status_code == expected


@pytest.mark.parametrize("status", ["draft", "retired"])
def test_unpublished_policy_is_inaccessible_even_to_hr(client, seeded, status):
    pid = seed_id("policy", "summit", "late-arrival", "1")
    seeded.execute(
        Policy.__table__.update().where(Policy.id == pid).values(status=status)
    )
    sign_in(client, "leila")
    assert client.get(f"/api/v1/policies/{pid}").status_code == 404


@pytest.mark.parametrize("username,days", [("maya", "12.00"), ("ravi", "5.00")])
def test_self_balance_from_sql(client, username, days):
    sign_in(client, username)
    response = client.get("/api/v1/leave/balance")
    assert response.status_code == 200
    assert response.json()["days_left"] == days


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_id", str(seed_id("company", "pebble"))),
        ("company", "pebble"),
        ("role", "hr"),
        ("user_id", str(seed_id("user", "pebble", "ravi"))),
    ],
)
def test_login_rejects_authority_fields(client, field, value):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "maya",
            "password": PASSWORD,
            field: value,
        },
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/me",
        "/api/v1/leave/balance",
        "/api/v1/policies/" + policy_id("summit", "late-arrival"),
    ],
)
@pytest.mark.parametrize("query", ["company_id=pebble", "role=hr", "user_id=ravi"])
def test_query_cannot_choose_identity(client, path, query):
    sign_in(client)
    assert client.get(path + "?" + query).status_code == 422


def test_headers_and_extra_cookies_cannot_select_identity(client):
    sign_in(client)
    client.cookies.set("role", "hr")
    client.cookies.set("company_id", "pebble")
    client.cookies.set("user_id", "ravi")
    response = client.get(
        "/api/v1/me",
        headers={
            "X-Company-Id": "pebble",
            "X-Role": "hr",
            "X-User-Id": "ravi",
            "Authorization": "Bearer forged-ravi-hr",
        },
    )
    assert response.status_code == 200
    assert response.json()["username"] == "maya"
    assert response.json()["company"]["slug"] == "summit"
    assert response.json()["role"] == "employee"
    assert "password" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/me",
        "/api/v1/leave/balance",
        "/api/v1/policies/" + policy_id("summit", "late-arrival"),
    ],
)
def test_missing_session_is_unauthorized(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("token", ["forged", "id.made-up", "..", "a." + "x" * 300])
def test_forged_session_is_rejected(client, token):
    assert (
        client.get(
            "/api/v1/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}
        ).status_code
        == 401
    )


def test_signed_cookie_tampering_is_rejected(client):
    sign_in(client)
    token = client.cookies.get(COOKIE_NAME)
    replacement = ("a" if token[0] != "a" else "b") + token[1:]
    assert (
        client.get(
            "/api/v1/me", headers={"Cookie": f"{COOKIE_NAME}={replacement}"}
        ).status_code
        == 401
    )


def test_forbidden_and_nonexistent_ids_are_non_enumerating(client):
    sign_in(client)
    denied = client.get("/api/v1/policies/" + policy_id("pebble", "late-arrival"))
    missing = client.get(f"/api/v1/policies/{uuid4()}")
    assert denied.status_code == missing.status_code == 404
    for key in ("code", "message"):
        assert denied.json()["error"][key] == missing.json()["error"][key]


@pytest.mark.parametrize(
    "username,password",
    [
        ("maya", "wrong-password"),
        ("missing", PASSWORD),
        ("' OR TRUE --", PASSWORD),
    ],
)
def test_invalid_credentials_have_generic_error(client, username, password):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid credentials"
    assert "password_hash" not in response.text


def test_duplicate_username_across_tenants_fails_closed(client, seeded):
    password_hash = seeded.execute(
        select(User.password_hash).where(User.id == seed_id("user", "summit", "maya"))
    ).scalar_one()
    seeded.execute(
        insert(User).values(
            company_id=seed_id("company", "pebble"),
            username="maya",
            role="employee",
            password_hash=password_hash,
        )
    )
    response = client.post(
        "/api/v1/auth/login", json={"username": "maya", "password": PASSWORD}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("target", ["user", "company"])
def test_disabled_identity_revokes_access_on_next_request(client, seeded, target):
    sign_in(client)
    if target == "user":
        seeded.execute(
            User.__table__.update()
            .where(User.id == seed_id("user", "summit", "maya"))
            .values(active=False)
        )
    else:
        seeded.execute(
            Company.__table__.update()
            .where(Company.id == seed_id("company", "summit"))
            .values(active=False)
        )
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "maya", "password": PASSWORD}
        ).status_code
        == 401
    )


def add_hr_probe(client):
    @client.app.get("/api/v1/_test/hr")
    def hr_probe(actor: Annotated[ActorContext, Depends(require_hr)]):
        return {"company_id": str(actor.company_id)}


@pytest.mark.parametrize(
    "username,status", [("maya", 403), ("leila", 200), ("ravi", 403)]
)
def test_hr_dependency_uses_server_role(client, username, status):
    add_hr_probe(client)
    sign_in(client, username)
    response = client.get(
        "/api/v1/_test/hr", headers={"X-Role": "hr", "X-Company-Id": "pebble"}
    )
    assert response.status_code == status
    if status == 200:
        assert response.json()["company_id"] == str(seed_id("company", "summit"))


def test_role_is_reloaded_instead_of_trusted_from_cookie(client, seeded):
    add_hr_probe(client)
    sign_in(client, "leila")
    assert client.get("/api/v1/_test/hr").status_code == 200
    seeded.execute(
        User.__table__.update()
        .where(User.id == seed_id("user", "summit", "leila"))
        .values(role="employee")
    )
    assert client.get("/api/v1/_test/hr").status_code == 403
    assert client.get("/api/v1/me").json()["role"] == "employee"


def test_cookie_flags_rotation_logout_and_replay(client):
    first = client.post(
        "/api/v1/auth/login", json={"username": "maya", "password": PASSWORD}
    )
    cookie = first.headers["set-cookie"].lower()
    for flag in (
        "httponly",
        "secure",
        "samesite=strict",
        "path=/api/v1",
        "max-age=1800",
    ):
        assert flag in cookie
    old = client.cookies.get(COOKIE_NAME)
    login = sign_in(client)
    token = client.cookies.get(COOKIE_NAME)
    assert old != token
    assert (
        client.get("/api/v1/me", headers={"Cookie": f"{COOKIE_NAME}={old}"}).status_code
        == 401
    )
    response = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": login["csrf_token"]}
    )
    assert response.status_code == 204
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.get(
            "/api/v1/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}
        ).status_code
        == 401
    )


@pytest.mark.parametrize("csrf", [None, "forged-token"])
def test_logout_requires_session_bound_csrf_token(client, csrf):
    sign_in(client)
    headers = {} if csrf is None else {"X-CSRF-Token": csrf}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert client.get("/api/v1/me").status_code == 200


def test_login_and_logout_require_exact_origin(client):
    for origin in ("https://evil.example", "null", "https://testserver.evil.example"):
        assert (
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": origin},
                json={"username": "maya", "password": PASSWORD},
            ).status_code
            == 403
        )
    login = sign_in(client)
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": login["csrf_token"],
            },
        ).status_code
        == 403
    )
    assert client.get("/api/v1/me").status_code == 200


def test_missing_origin_is_rejected(client):
    client.headers.pop("Origin")
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "maya", "password": PASSWORD}
        ).status_code
        == 403
    )


def test_logout_rejects_forged_body_fields(client):
    login = sign_in(client)
    assert (
        client.post(
            "/api/v1/auth/logout",
            json={"user_id": "ravi"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/me").status_code == 200


def test_expired_http_session_is_rejected(client):
    sign_in(client)
    client.app.state.sessions._clock = lambda: time.time() + 1900
    assert client.get("/api/v1/me").status_code == 401


def test_leila_has_no_implicit_balance_access(client):
    sign_in(client, "leila")
    assert client.get("/api/v1/leave/balance").status_code == 404


@pytest.mark.parametrize("username", ["maya", "leila", "ravi"])
def test_self_record_predicates_apply_to_every_role(seeded, username):
    actors = {}
    for person, company, role in [
        ("maya", "summit", "employee"),
        ("leila", "summit", "hr"),
        ("ravi", "pebble", "employee"),
    ]:
        actor = ActorContext(
            seed_id("user", company, person), seed_id("company", company), role
        )
        actors[person] = actor
        seeded.execute(
            insert(EmployeeProfile).values(
                company_id=actor.company_id,
                user_id=actor.user_id,
                display_name="Fictional test " + person,
                department="Fictional test",
                employment_start=date(2026, 1, 1),
            )
        )
        conversation = seeded.execute(
            insert(Conversation)
            .values(
                company_id=actor.company_id,
                owner_user_id=actor.user_id,
                title="Fictional test",
            )
            .returning(Conversation.id)
        ).scalar_one()
        task = seeded.execute(
            insert(Task)
            .values(
                company_id=actor.company_id,
                conversation_id=conversation,
                owner_user_id=actor.user_id,
                original_request="Fictional test",
            )
            .returning(Task.id)
        ).scalar_one()
        proposal = seeded.execute(
            insert(ActionProposal)
            .values(
                company_id=actor.company_id,
                task_id=task,
                owner_user_id=actor.user_id,
                action_type="test",
                payload={},
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            .returning(ActionProposal.id)
        ).scalar_one()
        request = seeded.execute(
            insert(LeaveRequest)
            .values(
                company_id=actor.company_id,
                user_id=actor.user_id,
                start_date=date(2026, 11, 9),
                end_date=date(2026, 11, 9),
                days=1,
                status="booked",
                confirmed_proposal_id=proposal,
            )
            .returning(LeaveRequest.id)
        ).scalar_one()
        seeded.execute(
            insert(LeaveHistory).values(
                company_id=actor.company_id,
                user_id=actor.user_id,
                actor_id=actor.user_id,
                request_id=request,
                event_type="fictional_test_" + person,
                days_delta=0,
            )
        )
    actor = actors[username]
    assert get_profile(seeded, actor)["display_name"] == "Fictional test " + username
    assert len(get_history(seeded, actor)) == 1
    assert get_history(seeded, actor)[0]["event_type"] == "fictional_test_" + username
    for other, subject in actors.items():
        if other != username:
            assert get_balance(seeded, actor, subject.user_id) is None
            assert get_profile(seeded, actor, subject.user_id) is None
            assert get_history(seeded, actor, subject.user_id) == []
    assert str(
        seeded.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar()
    ) in ("", "None")
