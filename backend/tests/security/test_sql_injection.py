"""SQL-looking text is search data; IDs/authority inputs never become SQL."""

import pytest
from sqlalchemy import select

from app.db.models import LeaveBalance, Policy, User

pytestmark = pytest.mark.integration


def test_sql_text_and_forged_ids_cannot_mutate_or_widen_scope(client, indexed):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "maya", "password": "ephemeral-test-password"},
    )
    assert response.status_code == 200
    balances = indexed.execute(
        select(LeaveBalance.user_id, LeaveBalance.days_left).order_by(
            LeaveBalance.user_id
        )
    ).all()
    users = indexed.execute(select(User.id).order_by(User.id)).all()
    policies = indexed.execute(
        select(Policy.id, Policy.source_sha256).order_by(Policy.id)
    ).all()
    attack = "'; UPDATE leave_balances SET days_left=999; DROP TABLE users; --"
    result = client.get("/api/v1/policies/search", params={"q": attack})
    assert result.status_code == 200
    assert all(
        s["citation"]["source_filename"].startswith("summit/")
        for s in result.json()["sources"]
    )
    assert client.get("/api/v1/policies/0%27%20OR%201%3D1--").status_code == 422
    assert (
        client.get(
            "/api/v1/leave/balance", params={"user_id": "' OR 1=1 --"}
        ).status_code
        == 422
    )
    assert (
        indexed.execute(
            select(LeaveBalance.user_id, LeaveBalance.days_left).order_by(
                LeaveBalance.user_id
            )
        ).all()
        == balances
    )
    assert indexed.execute(select(User.id).order_by(User.id)).all() == users
    assert (
        indexed.execute(
            select(Policy.id, Policy.source_sha256).order_by(Policy.id)
        ).all()
        == policies
    )
