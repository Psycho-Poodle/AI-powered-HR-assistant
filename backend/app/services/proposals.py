"""Transactional human-gated leave writes; never registered as an LLM tool."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Connection, func, insert, select, text, update

from app.db.models import (
    ActionProposal,
    AuditLog,
    Company,
    LeaveBalance,
    LeaveHistory,
    LeaveRequest,
    Task,
    User,
)
from app.schemas.hr import LeaveValidationInput
from app.schemas.proposals import (
    BookingResult,
    ProposalCreate,
    ProposalPayload,
    ProposalView,
)
from app.schemas.workflow import LeaveWorkflow
from app.security.authorization import ActorContext
from app.services.leave import HRToolError, validate_leave
from app.stream.events import proposal_changed

TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class ProposalFailure:
    status: int
    code: str


def lock_actor(connection: Connection, actor: ActorContext) -> bool:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(actor.company_id)},
    )
    return (
        connection.execute(
            select(User.id)
            .join(Company, Company.id == User.company_id)
            .where(
                User.id == actor.user_id,
                User.company_id == actor.company_id,
                User.role == actor.role,
                User.active.is_(True),
                Company.active.is_(True),
            )
            .with_for_update(read=True, of=(User, Company))
        ).first()
        is not None
    )


def owned_proposal(connection, actor, proposal_id, lock=False):
    query = select(ActionProposal.__table__).where(
        ActionProposal.id == proposal_id,
        ActionProposal.company_id == actor.company_id,
        ActionProposal.owner_user_id == actor.user_id,
        ActionProposal.action_type == "book_leave",
    )
    if lock:
        query = query.with_for_update()
    return connection.execute(query).mappings().one_or_none()


def view(row) -> ProposalView:
    payload = ProposalPayload.model_validate(row["payload"])
    return ProposalView(
        id=row["id"],
        task_id=row["task_id"],
        status=row["status"],
        version=row["version"],
        start_date=payload.start_date,
        end_date=payload.end_date,
        days=payload.days,
        expires_at=row["expires_at"],
    )


def expire_if_due(connection, row) -> ProposalFailure | None:
    # Real database time, evaluated AFTER waiting for the row lock.
    now = connection.execute(select(func.clock_timestamp())).scalar_one()
    if row["expires_at"] <= now:
        connection.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == row["id"],
                ActionProposal.company_id == row["company_id"],
                ActionProposal.owner_user_id == row["owner_user_id"],
                ActionProposal.status == "pending",
            )
            .values(status="expired", version=row["version"] + 1)
        )
        proposal_changed(connection, row, "expired", row["version"] + 1)
        return ProposalFailure(409, "expired")
    return None


def pending(connection, actor, proposal_id, expected_version):
    row = owned_proposal(connection, actor, proposal_id, lock=True)
    if row is None:
        return ProposalFailure(404, "not_found")
    if row["status"] != "pending":
        return ProposalFailure(409, "already_" + row["status"])
    expired = expire_if_due(connection, row)
    if expired:
        return expired
    if row["version"] != expected_version:
        return ProposalFailure(409, "stale_version")
    if row["action_type"] != "book_leave":
        return ProposalFailure(409, "unsupported_action")
    return row


def audit(connection, actor, proposal_id, action, version):
    connection.execute(
        insert(AuditLog.__table__).values(
            company_id=actor.company_id,
            actor_user_id=actor.user_id,
            action=action,
            object_type="action_proposal",
            object_id=proposal_id,
            outcome="success",
            metadata={"version": version},
        )
    )


def create_proposal(
    connection: Connection, actor: ActorContext, request: ProposalCreate
):
    if not lock_actor(connection, actor):
        return ProposalFailure(403, "forbidden")
    task = (
        connection.execute(
            select(Task.id, Task.plan, Task.instruction_revision)
            .where(
                Task.id == request.task_id,
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
                Task.status.in_(("completed", "awaiting_confirmation")),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if task is None:
        return ProposalFailure(404, "not_found")
    try:
        workflow = LeaveWorkflow.model_validate(
            task["plan"].get("execution", {}).get("workflow")
        )
    except ValidationError:
        return ProposalFailure(409, "leave_workflow_required")
    if (
        workflow.task_id != request.task_id
        or workflow.revision != task["instruction_revision"]
    ):
        return ProposalFailure(409, "leave_workflow_required")
    dates = LeaveValidationInput(
        start_date=request.start_date,
        end_date=request.end_date,
        leave_type=request.leave_type,
    )
    try:
        validation = validate_leave(connection, actor, dates)
    except HRToolError:
        return ProposalFailure(404, "not_found")
    if not validation.valid:
        return ProposalFailure(422, validation.errors[0])
    payload = ProposalPayload(**dates.model_dump(), days=validation.days)
    existing = (
        connection.execute(
            select(ActionProposal.__table__)
            .where(
                ActionProposal.company_id == actor.company_id,
                ActionProposal.owner_user_id == actor.user_id,
                ActionProposal.task_id == request.task_id,
                ActionProposal.action_type == "book_leave",
                ActionProposal.status == "pending",
            )
            .with_for_update()
        )
        .mappings()
        .all()
    )
    for row in existing:
        if expire_if_due(connection, row):
            continue
        if row["payload"] == payload.model_dump(mode="json"):
            return view(row)  # Repeat creation never creates a second active proposal.
        return ProposalFailure(409, "active_proposal_exists")
    identifier = uuid4()
    now = connection.execute(select(func.clock_timestamp())).scalar_one()
    connection.execute(
        insert(ActionProposal).values(
            id=identifier,
            company_id=actor.company_id,
            owner_user_id=actor.user_id,
            task_id=request.task_id,
            action_type="book_leave",
            payload=payload.model_dump(mode="json"),
            status="pending",
            version=1,
            expires_at=now + TTL,
        )
    )
    created = owned_proposal(connection, actor, identifier)
    proposal_changed(connection, created)
    return view(created)


def confirm_proposal(
    connection: Connection,
    actor: ActorContext,
    proposal_id: UUID,
    expected_version: int,
):
    if not lock_actor(connection, actor):
        return ProposalFailure(403, "forbidden")
    lock_proposal_task(connection, actor, proposal_id)
    row = pending(connection, actor, proposal_id, expected_version)
    if isinstance(row, ProposalFailure):
        return row
    owned_task = connection.execute(
        select(Task.id).where(
            Task.id == row["task_id"],
            Task.company_id == actor.company_id,
            Task.owner_user_id == actor.user_id,
            Task.status.in_(("completed", "awaiting_confirmation")),
        )
    ).first()
    if owned_task is None:
        return ProposalFailure(409, "task_unavailable")
    balance = (
        connection.execute(
            select(LeaveBalance.__table__)
            .where(
                LeaveBalance.company_id == actor.company_id,
                LeaveBalance.user_id == actor.user_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if balance is None:
        return ProposalFailure(404, "not_found")
    expired = expire_if_due(connection, row)
    if expired:
        return expired
    try:
        payload = ProposalPayload.model_validate(row["payload"])
    except ValidationError:
        return ProposalFailure(409, "invalid_payload")
    validation = validate_leave(
        connection,
        actor,
        LeaveValidationInput(
            start_date=payload.start_date,
            end_date=payload.end_date,
            leave_type=payload.leave_type,
        ),
    )
    if not validation.valid:
        return ProposalFailure(409, validation.errors[0])
    if payload.days != validation.days:
        return ProposalFailure(409, "invalid_payload")
    identifier, version = uuid4(), row["version"] + 1
    remaining = balance["days_left"] - validation.days
    # Savepoint makes every booking-side effect roll back even if an outer caller
    # catches a database error. API additionally commits the outer transaction
    # before sending a successful response.
    with connection.begin_nested():
        connection.execute(
            insert(LeaveRequest).values(
                id=identifier,
                company_id=actor.company_id,
                user_id=actor.user_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                days=validation.days,
                status="booked",
                confirmed_proposal_id=proposal_id,
            )
        )
        connection.execute(
            update(LeaveBalance)
            .where(
                LeaveBalance.id == balance["id"],
                LeaveBalance.company_id == actor.company_id,
                LeaveBalance.user_id == actor.user_id,
            )
            .values(
                days_left=remaining,
                version=balance["version"] + 1,
                updated_at=func.clock_timestamp(),
            )
        )
        connection.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == proposal_id,
                ActionProposal.company_id == actor.company_id,
                ActionProposal.owner_user_id == actor.user_id,
            )
            .values(
                status="confirmed", version=version, confirmed_at=func.clock_timestamp()
            )
        )
        connection.execute(
            insert(LeaveHistory).values(
                company_id=actor.company_id,
                user_id=actor.user_id,
                request_id=identifier,
                actor_id=actor.user_id,
                event_type="leave_booked",
                days_delta=-validation.days,
            )
        )
        audit(connection, actor, proposal_id, "leave.confirmed", version)
    proposal_changed(connection, row, "confirmed", version)
    return BookingResult(
        request_id=identifier,
        proposal_id=proposal_id,
        remaining_days=remaining,
        proposal_version=version,
    )


def cancel_proposal(
    connection: Connection,
    actor: ActorContext,
    proposal_id: UUID,
    expected_version: int,
):
    if not lock_actor(connection, actor):
        return ProposalFailure(403, "forbidden")
    lock_proposal_task(connection, actor, proposal_id)
    row = pending(connection, actor, proposal_id, expected_version)
    if isinstance(row, ProposalFailure):
        return row
    with connection.begin_nested():
        connection.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == proposal_id,
                ActionProposal.company_id == actor.company_id,
                ActionProposal.owner_user_id == actor.user_id,
            )
            .values(status="cancelled", version=row["version"] + 1)
        )
        audit(
            connection,
            actor,
            proposal_id,
            "leave.proposal_cancelled",
            row["version"] + 1,
        )
        proposal_changed(connection, row, "cancelled", row["version"] + 1)
    return view(owned_proposal(connection, actor, proposal_id))


def lock_proposal_task(connection, actor, proposal_id):
    # Keep task -> proposal -> balance lock order shared with notes/cancellation.
    connection.execute(
        select(Task.id)
        .join(
            ActionProposal,
            (ActionProposal.task_id == Task.id)
            & (ActionProposal.company_id == Task.company_id),
        )
        .where(
            ActionProposal.id == proposal_id,
            Task.company_id == actor.company_id,
            Task.owner_user_id == actor.user_id,
            ActionProposal.owner_user_id == actor.user_id,
        )
        .with_for_update(of=Task)
    ).first()
