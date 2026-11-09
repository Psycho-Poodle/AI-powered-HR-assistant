"""Exercise database-enforced tenant, uniqueness, RLS and history constraints."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.models import (
    ActionProposal,
    AuditLog,
    Conversation,
    EmployeeProfile,
    LeaveBalance,
    LeaveHistory,
    LeaveRequest,
    Message,
    Policy,
    PolicyChunk,
    Task,
    TaskEvent,
    TaskMessage,
)
from app.seed.load_seed import seed_id

pytestmark = pytest.mark.integration


def graph(db):
    """Valid Summit-only records to reference in constraint cases."""
    company = seed_id("company", "summit")
    user = seed_id("user", "summit", "maya")
    conversation = db.execute(
        insert(Conversation)
        .values(company_id=company, owner_user_id=user, title="Fictional test")
        .returning(Conversation.id)
    ).scalar_one()
    task = db.execute(
        insert(Task)
        .values(
            company_id=company,
            conversation_id=conversation,
            owner_user_id=user,
            original_request="Fictional test request",
        )
        .returning(Task.id)
    ).scalar_one()
    proposal = db.execute(
        insert(ActionProposal)
        .values(
            company_id=company,
            task_id=task,
            owner_user_id=user,
            action_type="book_leave",
            payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        .returning(ActionProposal.id)
    ).scalar_one()
    request = db.execute(
        insert(LeaveRequest)
        .values(
            company_id=company,
            user_id=user,
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 16),
            days=1,
            status="booked",
            confirmed_proposal_id=proposal,
        )
        .returning(LeaveRequest.id)
    ).scalar_one()
    return dict(
        company=company,
        user=user,
        conversation=conversation,
        task=task,
        proposal=proposal,
        request=request,
    )


CASES = [
    (EmployeeProfile, "user_id"),
    (Policy, "allowed_user_id"),
    (PolicyChunk, "policy_id"),
    (LeaveBalance, "user_id"),
    (Conversation, "owner_user_id"),
    (Message, "conversation_id"),
    (Task, "conversation_id"),
    (Task, "owner_user_id"),
    (TaskMessage, "task_id"),
    (TaskMessage, "user_id"),
    (TaskEvent, "task_id"),
    (ActionProposal, "task_id"),
    (ActionProposal, "owner_user_id"),
    (LeaveRequest, "user_id"),
    (LeaveRequest, "confirmed_proposal_id"),
    (LeaveHistory, "user_id"),
    (LeaveHistory, "actor_id"),
    (LeaveHistory, "request_id"),
    (AuditLog, "actor_user_id"),
]


@pytest.mark.parametrize(
    "model,column", CASES, ids=[f"{m.__tablename__}.{c}" for m, c in CASES]
)
def test_every_tenant_foreign_key_rejects_other_company(seeded, model, column):
    g = graph(seeded)
    # Entire insert belongs to Pebble, but exactly the tested parent points to Summit.
    pebble = seed_id("company", "pebble")
    ravi = seed_id("user", "pebble", "ravi")
    other_conversation = seeded.execute(
        insert(Conversation)
        .values(company_id=pebble, owner_user_id=ravi, title="Fictional Pebble test")
        .returning(Conversation.id)
    ).scalar_one()
    other_task = seeded.execute(
        insert(Task)
        .values(
            company_id=pebble,
            conversation_id=other_conversation,
            owner_user_id=ravi,
            original_request="Fictional Pebble test",
        )
        .returning(Task.id)
    ).scalar_one()
    other_proposal = seeded.execute(
        insert(ActionProposal)
        .values(
            company_id=pebble,
            task_id=other_task,
            owner_user_id=ravi,
            action_type="book_leave",
            payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        .returning(ActionProposal.id)
    ).scalar_one()
    other_request = seeded.execute(
        insert(LeaveRequest)
        .values(
            company_id=pebble,
            user_id=ravi,
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 16),
            days=1,
            status="booked",
            confirmed_proposal_id=other_proposal,
        )
        .returning(LeaveRequest.id)
    ).scalar_one()
    # Existing balance/proposal references must not win with uniqueness violations.
    if model == LeaveBalance:
        seeded.execute(text("DELETE FROM leave_balances WHERE user_id=:u"), {"u": ravi})
    values = {
        EmployeeProfile: dict(
            user_id=ravi,
            display_name="Fictional",
            department="Demo",
            employment_start=date(2026, 1, 1),
        ),
        Policy: dict(
            slug="test-restricted",
            title="Fictional",
            body="Fictional",
            visibility="specific_user",
            allowed_user_id=ravi,
            version=1,
            status="draft",
            source_filename="test",
            source_sha256="a" * 64,
            provenance="fictional_demo",
            is_demo=True,
        ),
        PolicyChunk: dict(
            policy_id=seed_id("policy", "pebble", "late-arrival", "1"),
            chunk_no=0,
            chunk_text="Fictional",
            embedding=[0.0] * 384,
        ),
        LeaveBalance: dict(user_id=ravi, days_left=5),
        Conversation: dict(owner_user_id=ravi, title="Fictional"),
        Message: dict(
            conversation_id=other_conversation, sender="user", body="Fictional"
        ),
        Task: dict(
            conversation_id=other_conversation,
            owner_user_id=ravi,
            original_request="Fictional",
        ),
        TaskMessage: dict(
            task_id=other_task, user_id=ravi, instruction="Fictional", revision=1
        ),
        TaskEvent: dict(task_id=other_task, seq=1, event_type="test", payload={}),
        ActionProposal: dict(
            task_id=other_task,
            owner_user_id=ravi,
            action_type="test",
            payload={},
            expires_at=datetime.now(UTC),
        ),
        LeaveRequest: dict(
            user_id=ravi,
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 16),
            days=1,
            status="booked",
            confirmed_proposal_id=other_proposal,
        ),
        LeaveHistory: dict(
            user_id=ravi,
            actor_id=ravi,
            request_id=other_request,
            event_type="test",
            days_delta=0,
        ),
        AuditLog: dict(
            actor_user_id=ravi,
            action="test",
            object_type="test",
            object_id=uuid4(),
            outcome="test",
            metadata={},
        ),
    }[model]
    # Ensure the new request uses a fresh valid proposal except when testing its FK.
    if model == LeaveRequest:
        fresh = seeded.execute(
            insert(ActionProposal)
            .values(
                company_id=pebble,
                task_id=other_task,
                owner_user_id=ravi,
                action_type="test",
                payload={},
                expires_at=datetime.now(UTC),
            )
            .returning(ActionProposal.id)
        ).scalar_one()
        values["confirmed_proposal_id"] = fresh
    parent = {
        "user_id": g["user"],
        "owner_user_id": g["user"],
        "allowed_user_id": g["user"],
        "actor_id": g["user"],
        "actor_user_id": g["user"],
        "conversation_id": g["conversation"],
        "task_id": g["task"],
        "request_id": g["request"],
        "policy_id": seed_id("policy", "summit", "late-arrival", "1"),
        "confirmed_proposal_id": g["proposal"],
    }[column]
    if column == "confirmed_proposal_id":
        # Remove the existing Summit booking so uniqueness does not mask the FK.
        seeded.execute(
            text("DELETE FROM leave_requests WHERE id=:id"), {"id": g["request"]}
        )
    values[column] = parent
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(insert(model.__table__).values(company_id=pebble, **values))
    assert error.value.orig.sqlstate == "23503"


@pytest.mark.parametrize(
    "table", ["task_messages", "task_events", "leave_history", "audit_logs"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_history_is_append_only(seeded, table, operation):
    g = graph(seeded)
    entries = {
        "task_messages": (
            TaskMessage,
            dict(task_id=g["task"], user_id=g["user"], instruction="test", revision=1),
        ),
        "task_events": (
            TaskEvent,
            dict(task_id=g["task"], seq=1, event_type="test", payload={}),
        ),
        "leave_history": (
            LeaveHistory,
            dict(
                user_id=g["user"],
                actor_id=g["user"],
                request_id=g["request"],
                event_type="test",
                days_delta=0,
            ),
        ),
        "audit_logs": (
            AuditLog,
            dict(
                actor_user_id=g["user"],
                action="test",
                object_type="test",
                object_id=uuid4(),
                outcome="test",
                metadata={},
            ),
        ),
    }
    model, values = entries[table]
    seeded.execute(insert(model.__table__).values(company_id=g["company"], **values))
    statement = {
        "UPDATE": f"UPDATE {table} SET id=id",
        "DELETE": f"DELETE FROM {table}",
        "TRUNCATE": f"TRUNCATE {table}",
    }[operation]
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(text(statement))
    assert error.value.orig.sqlstate == "23514"


def test_unique_event_sequence_and_proposal_booking(seeded):
    g = graph(seeded)
    event = dict(
        company_id=g["company"], task_id=g["task"], seq=1, event_type="test", payload={}
    )
    seeded.execute(insert(TaskEvent).values(**event))
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(insert(TaskEvent).values(**event))
    assert error.value.orig.sqlstate == "23505"
    request = (
        seeded.execute(
            select(LeaveRequest.__table__).where(LeaveRequest.id == g["request"])
        )
        .mappings()
        .one()
    )
    values = dict(request)
    values.pop("id")
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(insert(LeaveRequest).values(**values))
    assert error.value.orig.sqlstate == "23505"


def test_negative_balance_and_invalid_dates(seeded):
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(text("UPDATE leave_balances SET days_left=-1"))
    assert error.value.orig.sqlstate == "23514"
    g = graph(seeded)
    with pytest.raises(IntegrityError) as error, seeded.begin_nested():
        seeded.execute(
            text("UPDATE leave_requests SET end_date=start_date-1 WHERE id=:id"),
            {"id": g["request"]},
        )
    assert error.value.orig.sqlstate == "23514"


def test_immutable_original_request_and_creation_time(seeded):
    g = graph(seeded)
    for statement in (
        "UPDATE tasks SET original_request='replacement'",
        "UPDATE tasks SET created_at=created_at + interval '1 second'",
        "UPDATE policies SET ingested_at=ingested_at + interval '1 second'",
    ):
        with pytest.raises(IntegrityError) as error, seeded.begin_nested():
            seeded.execute(text(statement))
        assert error.value.orig.sqlstate == "23514"
    assert (
        seeded.execute(
            select(Task.original_request).where(Task.id == g["task"])
        ).scalar()
        == "Fictional test request"
    )


def test_rls_fails_closed_and_restricts_tenant_for_nonprivileged_role(seeded):
    assert (
        seeded.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                "AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        ).scalar()
        == 14
    )
    role = "phase2_rls_" + uuid4().hex
    seeded.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
    seeded.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
    seeded.execute(text(f'GRANT SELECT, INSERT ON users TO "{role}"'))
    seeded.execute(text(f'SET LOCAL ROLE "{role}"'))
    assert seeded.execute(text("SELECT count(*) FROM users")).scalar() == 0
    seeded.execute(
        text("SELECT set_config('app.tenant_id', :id, true)"),
        {"id": str(seed_id("company", "summit"))},
    )
    assert seeded.execute(
        text("SELECT username FROM users ORDER BY username")
    ).all() == [
        ("leila",),
        ("maya",),
    ]
    with pytest.raises(DBAPIError) as error, seeded.begin_nested():
        seeded.execute(
            text(
                "INSERT INTO users (company_id,username,password_hash,role) "
                "VALUES (:company,'forged','not-a-real-password','employee')"
            ),
            {"company": seed_id("company", "pebble")},
        )
    assert error.value.orig.sqlstate == "42501"
    seeded.execute(text("RESET ROLE"))
