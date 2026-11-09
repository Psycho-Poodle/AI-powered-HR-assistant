"""HTTP search and ingestion must preserve the Phase 3 actor/CSRF boundary."""

import pytest
from sqlalchemy import select

from app.api import policies
from app.db.models import Policy
from app.rag.embeddings import EmbeddingUnavailable
from app.seed.load_seed import seed_id

pytestmark = pytest.mark.integration


def sign_in(client, username="leila"):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "ephemeral-test-password"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def body(**changes):
    return (
        dict(
            slug="api-policy",
            title="FICTIONAL DEMONSTRATION DATA",
            markdown="# FICTIONAL DEMONSTRATION DATA\nAnnual leave test rules.",
            source_filename="api.md",
            version=1,
        )
        | changes
    )


def test_search_uses_authenticated_scope_and_citations(client, indexed):
    sign_in(client, "maya")
    response = client.get("/api/v1/policies/search", params={"q": "late three times"})
    assert response.status_code == 200
    assert response.json()["status"] == "sources_found"
    assert any("one-day pay cut" in s["text"] for s in response.json()["sources"])
    assert all(
        s["citation"]["source_filename"].startswith("summit/")
        for s in response.json()["sources"]
    )
    assert "warning only" not in response.text


@pytest.mark.parametrize(
    "params",
    [
        {"q": "late", "company_id": "pebble"},
        {"q": "late", "role": "hr"},
        {"q": "late", "user_id": "leila"},
        {"q": "late", "limit": 21},
        {"q": " "},
    ],
)
def test_search_rejects_spoofed_scope_and_invalid_input(client, params):
    sign_in(client, "maya")
    assert client.get("/api/v1/policies/search", params=params).status_code == 422


def test_unauthenticated_search_is_denied(client):
    assert client.get("/api/v1/policies/search?q=late").status_code == 401


def test_hr_markdown_ingestion_and_repeat(client):
    headers = sign_in(client)
    first = client.post("/api/v1/policies/ingest", json=body(), headers=headers)
    assert first.status_code == 200 and first.json()["changed"]
    second = client.post("/api/v1/policies/ingest", json=body(), headers=headers)
    assert second.status_code == 200 and not second.json()["changed"]
    changed = client.post(
        "/api/v1/policies/ingest", json=body(visibility="hr"), headers=headers
    )
    assert changed.status_code == 409


@pytest.mark.parametrize("username", ["maya", "ravi"])
def test_employee_cannot_ingest(client, username):
    headers = sign_in(client, username)
    assert (
        client.post("/api/v1/policies/ingest", json=body(), headers=headers).status_code
        == 403
    )


def test_ingestion_requires_csrf(client):
    sign_in(client)
    assert client.post("/api/v1/policies/ingest", json=body()).status_code == 403


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"company_id": "pebble"}, 422),
        ({"role": "hr"}, 422),
        ({"source_filename": "../outside.md"}, 422),
        ({"source_filename": "policy.txt"}, 422),
        ({"provenance": "assignment"}, 403),
        ({"title": "not labelled"}, 422),
        (
            {
                "visibility": "specific_user",
                "allowed_user_id": str(seed_id("user", "pebble", "ravi")),
            },
            403,
        ),
    ],
)
def test_ingest_rejects_scope_provenance_and_source_spoofing(client, changes, status):
    headers = sign_in(client)
    assert (
        client.post(
            "/api/v1/policies/ingest", json=body(**changes), headers=headers
        ).status_code
        == status
    )


def test_model_unavailable_is_explicit_and_does_not_publish(
    client, seeded, monkeypatch
):
    headers = sign_in(client)

    def unavailable():
        raise EmbeddingUnavailable("no cache")

    monkeypatch.setattr(policies, "get_embeddings", unavailable)
    assert client.get("/api/v1/policies/search?q=leave").status_code == 503
    assert (
        client.post("/api/v1/policies/ingest", json=body(), headers=headers).status_code
        == 503
    )
    assert (
        seeded.execute(select(Policy.id).where(Policy.slug == "api-policy")).first()
        is None
    )
