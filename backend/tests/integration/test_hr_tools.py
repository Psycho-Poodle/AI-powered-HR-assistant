"""Authorized SQL tools and read-only validation against real PostgreSQL."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, text

from app.db.base import Base
from app.db.models import (
    ActionProposal,
    Conversation,
    EmployeeProfile,
    LeaveHistory,
    LeaveRequest,
    Task,
)
from app.schemas.hr import LeaveValidationInput
from app.security.authorization import ActorContext
from app.seed.load_seed import seed_id
from app.services.leave import HRToolError, encode_cursor
from app.tools.leave import (
    get_employee_profile,
    get_leave_balance,
    get_leave_history,
    validate_leave_request,
)

pytestmark = pytest.mark.integration


def actor(username="maya"):
    company = "pebble" if username == "ravi" else "summit"
    return ActorContext(
        seed_id("user", company, username),
        seed_id("company", company),
        "hr" if username == "leila" else "employee",
    )


def booked(
    db, person, start=date(2026, 11, 16), end=date(2026, 11, 18), status="booked"
):
    context = actor(person)
    conversation = db.execute(
        insert(Conversation)
        .values(
            company_id=context.company_id,
            owner_user_id=context.user_id,
            title="Fictional test",
        )
        .returning(Conversation.id)
    ).scalar_one()
    task = db.execute(
        insert(Task)
        .values(
            company_id=context.company_id,
            owner_user_id=context.user_id,
            conversation_id=conversation,
            original_request="Fictional test",
        )
        .returning(Task.id)
    ).scalar_one()
    proposal = db.execute(
        insert(ActionProposal)
        .values(
            company_id=context.company_id,
            owner_user_id=context.user_id,
            task_id=task,
            action_type="fictional_test",
            payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        .returning(ActionProposal.id)
    ).scalar_one()
    return db.execute(
        insert(LeaveRequest)
        .values(
            company_id=context.company_id,
            user_id=context.user_id,
            start_date=start,
            end_date=end,
            days=1,
            status=status,
            confirmed_proposal_id=proposal,
        )
        .returning(LeaveRequest.id)
    ).scalar_one()


@pytest.mark.parametrize("person,days", [("maya", 12), ("ravi", 5)])
def test_exact_seed_balances_are_typed_sql_reads(seeded, person, days):
    result = get_leave_balance(seeded, actor(person))
    assert result.days_left == Decimal(days) and result.as_of.tzinfo is not None


@pytest.mark.parametrize(
    "person,other",
    [("maya", "ravi"), ("maya", "leila"), ("leila", "maya"), ("leila", "ravi")],
)
def test_all_tools_reject_another_subject_even_for_hr(seeded, person, other):
    context, subject = actor(person), actor(other).user_id
    functions = [
        lambda: get_leave_balance(seeded, context, subject),
        lambda: get_employee_profile(seeded, context, subject),
        lambda: get_leave_history(seeded, context, subject_id=subject),
        lambda: validate_leave_request(
            seeded,
            context,
            LeaveValidationInput(start_date="2026-11-09", end_date="2026-11-11"),
            subject_id=subject,
        ),
    ]
    for call in functions:
        with pytest.raises(HRToolError) as error:
            call()
        assert error.value.code == "forbidden"


def test_profile_missing_record_and_safe_fields(seeded):
    with pytest.raises(HRToolError) as error:
        get_employee_profile(seeded, actor())
    assert error.value.code == "not_found"
    seeded.execute(
        insert(EmployeeProfile).values(
            company_id=actor().company_id,
            user_id=actor().user_id,
            display_name="Fictional Maya",
            department="Demo",
            employment_start=date(2026, 1, 1),
        )
    )
    result = get_employee_profile(seeded, actor())
    assert result.display_name == "Fictional Maya"
    assert "password_hash" not in result.model_dump()
    with pytest.raises(HRToolError) as error:
        get_leave_balance(seeded, actor("leila"))
    assert error.value.code == "not_found"


def test_history_cursor_ties_and_tenant_scope(seeded):
    timestamp = datetime(2026, 11, 8, tzinfo=UTC)
    for person in ("maya", "leila", "ravi"):
        request = booked(seeded, person)
        context = actor(person)
        for number in range(3):
            seeded.execute(
                insert(LeaveHistory).values(
                    id=uuid4(),
                    company_id=context.company_id,
                    user_id=context.user_id,
                    actor_id=context.user_id,
                    request_id=request,
                    event_type=f"fictional_{person}_{number}",
                    days_delta=0,
                    occurred_at=timestamp,
                )
            )
    first = get_leave_history(seeded, actor(), limit=2)
    assert len(first.items) == 2 and first.next_cursor
    second = get_leave_history(seeded, actor(), limit=2, cursor=first.next_cursor)
    assert len(second.items) == 1 and second.next_cursor is None
    items = first.items + second.items
    assert len({item.id for item in items}) == 3
    assert all("maya" in item.event_type for item in items)
    assert [item.id for item in items] == sorted(
        (item.id for item in items), reverse=True
    )
    assert (
        get_leave_history(
            seeded, actor(), limit=2, cursor=encode_cursor(second.items[-1])
        ).items
        == ()
    )
    with pytest.raises(HRToolError) as error:
        get_leave_history(seeded, actor(), cursor="' OR TRUE --")
    assert error.value.code == "invalid_cursor"


@pytest.mark.parametrize(
    "person,start,end,errors",
    [
        ("maya", "2026-11-09", "2026-11-11", ()),
        ("ravi", "2026-11-09", "2026-11-16", ("insufficient_balance",)),
        ("maya", "2026-11-14", "2026-11-15", ("no_workdays",)),
        ("maya", "2026-11-11", "2026-11-09", ("date_order",)),
        ("maya", "2026-01-01", "2027-01-02", ("range_too_long",)),
    ],
)
def test_validation_results_and_demo_label(seeded, person, start, end, errors):
    result = validate_leave_request(
        seeded, actor(person), LeaveValidationInput(start_date=start, end_date=end)
    )
    assert result.errors == errors and result.valid == (not errors)
    assert "FICTIONAL DEMONSTRATION CONVENTION" in result.convention
    if not errors:
        assert result.days == 3 and result.available_days == 12


@pytest.mark.parametrize(
    "status,overlap", [("booked", True), ("pending", True), ("cancelled", False)]
)
def test_overlap_is_self_only_inclusive_and_ignores_cancelled(seeded, status, overlap):
    booked(seeded, "maya", status=status)
    booked(seeded, "ravi")
    booked(seeded, "leila")
    result = validate_leave_request(
        seeded,
        actor(),
        LeaveValidationInput(start_date="2026-11-18", end_date="2026-11-20"),
    )
    assert result.overlaps_existing == overlap
    assert ("overlap" in result.errors) == overlap


def test_other_tenant_and_other_employee_overlap_is_not_disclosed(seeded):
    booked(seeded, "ravi")
    booked(seeded, "leila")
    result = validate_leave_request(
        seeded,
        actor(),
        LeaveValidationInput(start_date="2026-11-16", end_date="2026-11-18"),
    )
    assert result.valid and not result.overlaps_existing


def test_all_hr_operations_leave_all_rows_unchanged(seeded):
    def snapshot():
        return {
            name: seeded.execute(
                text(f'SELECT row_to_json(t)::text FROM "{name}" t ORDER BY id')
            ).all()
            for name in Base.metadata.tables
        }

    before = snapshot()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(seeded, "before_cursor_execute", capture)
    try:
        get_leave_balance(seeded, actor())
        get_leave_history(seeded, actor())
        for start, end in [("2026-11-09", "2026-11-11"), ("2026-11-14", "2026-11-15")]:
            validate_leave_request(
                seeded, actor(), LeaveValidationInput(start_date=start, end_date=end)
            )
    finally:
        event.remove(seeded, "before_cursor_execute", capture)
    assert all(statement.startswith("SELECT") for statement in statements)
    assert snapshot() == before
