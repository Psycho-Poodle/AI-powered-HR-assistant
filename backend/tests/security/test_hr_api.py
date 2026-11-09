"""HTTP identity spoofing, CSRF and predictable validation errors."""

import pytest

pytestmark = pytest.mark.integration


def login(client, username="maya"):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "ephemeral-test-password"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.mark.parametrize("username,days", [("maya", "12.00"), ("ravi", "5.00")])
def test_balance_contract_is_preserved(client, username, days):
    login(client, username)
    response = client.get("/api/v1/leave/balance")
    assert response.status_code == 200 and response.json()["days_left"] == days


@pytest.mark.parametrize("path", ["/api/v1/employee/profile", "/api/v1/leave/history"])
def test_reads_require_authentication(client, path):
    assert client.get(path).status_code == 401


def test_empty_self_history_and_missing_profile(client):
    login(client)
    assert client.get("/api/v1/leave/history").json() == {
        "items": [],
        "next_cursor": None,
    }
    assert client.get("/api/v1/employee/profile").status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "user_id=ravi",
        "role=hr",
        "company_id=pebble",
        "limit=0",
        "limit=101",
        "cursor=%27%20OR%20TRUE--",
    ],
)
def test_history_rejects_spoofing_and_invalid_pagination(client, query):
    login(client)
    assert client.get("/api/v1/leave/history?" + query).status_code == 422


def test_read_only_validation_endpoint_requires_csrf_and_returns_demo_label(client):
    headers = login(client)
    body = {"start_date": "2026-11-09", "end_date": "2026-11-11"}
    assert client.post("/api/v1/leave/validate", json=body).status_code == 403
    response = client.post("/api/v1/leave/validate", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["valid"]
    assert response.json()["days"] == "3"
    assert "FICTIONAL DEMONSTRATION CONVENTION" in response.json()["convention"]
    assert client.get("/api/v1/leave/balance").json()["days_left"] == "12.00"


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": "ravi"},
        {"company_id": "pebble"},
        {"role": "hr"},
        {"leave_type": "sick"},
    ],
)
def test_validation_rejects_authority_fields_and_unsupported_leave_type(client, extra):
    headers = login(client)
    response = client.post(
        "/api/v1/leave/validate",
        json={"start_date": "2026-11-09", "end_date": "2026-11-11", **extra},
        headers=headers,
    )
    assert response.status_code == 422


def test_business_invalid_result_is_distinct_from_malformed_input(client):
    headers = login(client, "ravi")
    result = client.post(
        "/api/v1/leave/validate",
        json={"start_date": "2026-11-09", "end_date": "2026-11-16"},
        headers=headers,
    )
    assert result.status_code == 200
    assert result.json()["errors"] == ["insufficient_balance"]
    assert not result.json()["valid"]
    assert (
        client.post(
            "/api/v1/leave/validate",
            json={"start_date": "not-a-date", "end_date": "2026-11-16"},
            headers=headers,
        ).status_code
        == 422
    )


def test_hr_does_not_inherit_missing_self_balance(client):
    headers = login(client, "leila")
    assert (
        client.post(
            "/api/v1/leave/validate",
            json={"start_date": "2026-11-09", "end_date": "2026-11-11"},
            headers=headers,
        ).status_code
        == 404
    )
