"""Real concurrent transactions, locking, versioning and atomic booking effects."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    ActionProposal,
    AuditLog,
    LeaveBalance,
    LeaveHistory,
    LeaveRequest,
    Task,
)
from app.schemas.proposals import ProposalCreate
from app.security.authorization import ActorContext
from app.seed.load_seed import seed_id
from app.services.proposals import (
    ProposalFailure,
    cancel_proposal,
    confirm_proposal,
    create_proposal,
)

pytestmark = pytest.mark.integration


def actor(person="maya"):
    company = "pebble" if person == "ravi" else "summit"
    return ActorContext(
        seed_id("user", company, person),
        seed_id("company", company),
        "hr" if person == "leila" else "employee",
    )


def create(engine, start="2026-11-09", end="2026-11-11", task_id=None):
    with engine.begin() as connection:
        return create_proposal(
            connection,
            actor(),
            ProposalCreate(
                task_id=task_id or seed_id("proposal-test-task", "maya"),
                start_date=start,
                end_date=end,
            ),
        )


def confirm(engine, proposal, version=1):
    with engine.begin() as connection:
        return confirm_proposal(connection, actor(), proposal, version)


def counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.execute(select(func.count()).select_from(model)).scalar()
            for model in (LeaveRequest, LeaveHistory, AuditLog)
        )


def balance(engine):
    with engine.connect() as connection:
        return connection.execute(
            select(LeaveBalance.days_left).where(
                LeaveBalance.user_id == actor().user_id
            )
        ).scalar_one()


def extra_task(engine):
    identifier = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(Task).values(
                id=identifier,
                company_id=actor().company_id,
                owner_user_id=actor().user_id,
                conversation_id=seed_id("proposal-test-conversation", "maya"),
                original_request="Fictional second proposal",
                status="completed",
            )
        )
    return identifier


def test_create_repeat_confirm_and_duplicate_exactly_once(booking_engine):
    proposal = create(booking_engine)
    assert proposal.status == "pending" and proposal.days == 3 and proposal.version == 1
    assert create(booking_engine).id == proposal.id
    assert balance(booking_engine) == 12 and counts(booking_engine) == (0, 0, 0)
    result = confirm(booking_engine, proposal.id)
    assert (
        result.status == "booked"
        and result.remaining_days == 9
        and result.proposal_version == 2
    )
    assert counts(booking_engine) == (1, 1, 1) and balance(booking_engine) == 9
    duplicate = confirm(booking_engine, proposal.id)
    assert duplicate == ProposalFailure(409, "already_confirmed")
    assert counts(booking_engine) == (1, 1, 1) and balance(booking_engine) == 9
    with booking_engine.connect() as connection:
        assert connection.execute(select(LeaveHistory.days_delta)).scalar_one() == -3
        assert (
            connection.execute(
                select(LeaveBalance.version).where(
                    LeaveBalance.user_id == actor().user_id
                )
            ).scalar_one()
            == 2
        )


def test_concurrent_duplicate_confirmation(booking_engine):
    proposal = create(booking_engine)
    gate = threading.Barrier(2, timeout=10)

    def attempt():
        gate.wait()
        return confirm(booking_engine, proposal.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(not isinstance(r, ProposalFailure) for r in results) == 1
    assert counts(booking_engine) == (1, 1, 1) and balance(booking_engine) == 9


@pytest.mark.parametrize("overlapping", [False, True])
def test_distinct_proposals_serialize_on_balance_and_revalidate(
    booking_engine, overlapping
):
    with booking_engine.begin() as connection:
        connection.execute(
            update(LeaveBalance)
            .where(LeaveBalance.user_id == actor().user_id)
            .values(days_left=5 if not overlapping else 12)
        )
    first = create(booking_engine)
    second = create(
        booking_engine,
        start="2026-11-09" if overlapping else "2026-11-16",
        end="2026-11-11" if overlapping else "2026-11-18",
        task_id=extra_task(booking_engine),
    )
    gate = threading.Barrier(2, timeout=10)

    def attempt(proposal):
        gate.wait()
        return confirm(booking_engine, proposal.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    assert sum(not isinstance(r, ProposalFailure) for r in results) == 1
    assert next(r for r in results if isinstance(r, ProposalFailure)).code == (
        "overlap" if overlapping else "insufficient_balance"
    )
    assert counts(booking_engine) == (1, 1, 1)
    assert balance(booking_engine) == (9 if overlapping else 2)


def test_stale_expired_and_cancelled_states(booking_engine):
    proposal = create(booking_engine)
    assert confirm(booking_engine, proposal.id, 9) == ProposalFailure(
        409, "stale_version"
    )
    with booking_engine.begin() as connection:
        result = cancel_proposal(connection, actor(), proposal.id, 1)
    assert result.status == "cancelled" and result.version == 2
    assert confirm(booking_engine, proposal.id) == ProposalFailure(
        409, "already_cancelled"
    )
    another = create(booking_engine)
    with booking_engine.begin() as connection:
        connection.execute(
            update(ActionProposal)
            .where(ActionProposal.id == another.id)
            .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert confirm(booking_engine, another.id) == ProposalFailure(409, "expired")
    with booking_engine.connect() as connection:
        row = connection.execute(
            select(ActionProposal.status, ActionProposal.version).where(
                ActionProposal.id == another.id
            )
        ).one()
        assert row == ("expired", 2)
    assert balance(booking_engine) == 12


def test_confirm_cancel_race_has_one_terminal_winner(booking_engine):
    proposal = create(booking_engine)
    gate = threading.Barrier(2, timeout=10)

    def attempt(cancel):
        gate.wait()
        with booking_engine.begin() as connection:
            return (cancel_proposal if cancel else confirm_proposal)(
                connection, actor(), proposal.id, 1
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (False, True)))
    assert sum(isinstance(r, ProposalFailure) for r in results) == 1
    with booking_engine.connect() as connection:
        state = connection.execute(
            select(ActionProposal.status).where(ActionProposal.id == proposal.id)
        ).scalar_one()
    assert state in ("confirmed", "cancelled")
    assert balance(booking_engine) == (9 if state == "confirmed" else 12)
    assert counts(booking_engine) == ((1, 1, 1) if state == "confirmed" else (0, 0, 1))


def test_expiry_is_checked_again_after_waiting_for_balance(booking_engine):
    proposal = create(booking_engine)
    with booking_engine.begin() as connection:
        deadline = connection.execute(
            select(func.clock_timestamp())
        ).scalar_one() + timedelta(seconds=3)
        connection.execute(
            update(ActionProposal)
            .where(ActionProposal.id == proposal.id)
            .values(expires_at=deadline)
        )
    waiting = threading.Event()

    def observe(conn, cursor, statement, params, context, many):
        if "leave_balances" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with booking_engine.connect() as held:
        transaction = held.begin()
        held.execute(
            select(LeaveBalance.id)
            .where(LeaveBalance.user_id == actor().user_id)
            .with_for_update()
        )
        event.listen(booking_engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(confirm, booking_engine, proposal.id)
                try:
                    assert waiting.wait(5)
                    now = held.execute(select(func.clock_timestamp())).scalar_one()
                    time.sleep(max(0, (deadline - now).total_seconds()) + 0.05)
                finally:
                    transaction.rollback()
                assert future.result(timeout=10) == ProposalFailure(409, "expired")
        finally:
            if transaction.is_active:
                transaction.rollback()
            event.remove(booking_engine, "before_cursor_execute", observe)
    assert balance(booking_engine) == 12 and counts(booking_engine) == (0, 0, 0)


def test_database_failure_rolls_back_all_booking_side_effects(booking_engine):
    proposal = create(booking_engine)

    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO audit_logs"):
            raise RuntimeError("injected final write failure")

    event.listen(booking_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises((RuntimeError, SQLAlchemyError)):
            confirm(booking_engine, proposal.id)
    finally:
        event.remove(booking_engine, "before_cursor_execute", fail)
    assert balance(booking_engine) == 12 and counts(booking_engine) == (0, 0, 0)
    with booking_engine.connect() as connection:
        assert (
            connection.execute(
                select(ActionProposal.status).where(ActionProposal.id == proposal.id)
            ).scalar_one()
            == "pending"
        )


def test_payload_tampering_and_changed_balance_are_rejected(booking_engine):
    proposal = create(booking_engine)
    with booking_engine.begin() as connection:
        payload = dict(
            connection.execute(
                select(ActionProposal.payload).where(ActionProposal.id == proposal.id)
            ).scalar_one()
        )
        payload["days"] = "1"
        connection.execute(
            update(ActionProposal)
            .where(ActionProposal.id == proposal.id)
            .values(payload=payload)
        )
    assert confirm(booking_engine, proposal.id) == ProposalFailure(
        409, "invalid_payload"
    )
    assert balance(booking_engine) == 12 and counts(booking_engine) == (0, 0, 0)
