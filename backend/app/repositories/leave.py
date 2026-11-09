"""Self-only record predicates, including when the caller has the HR role."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Connection, select, tuple_

from app.db.models import EmployeeProfile, LeaveBalance, LeaveHistory, LeaveRequest
from app.security.authorization import ActorContext


def self_scope(model, actor: ActorContext, subject_id: UUID | None):
    # Both predicates are intentional: specifying another subject cannot widen scope.
    return (
        model.company_id == actor.company_id,
        model.user_id == actor.user_id,
        model.user_id == (subject_id if subject_id is not None else actor.user_id),
    )


def get_balance(
    connection: Connection, actor: ActorContext, subject_id: UUID | None = None
):
    return (
        connection.execute(
            select(
                LeaveBalance.days_left,
                LeaveBalance.updated_at.label("as_of"),
            ).where(*self_scope(LeaveBalance, actor, subject_id))
        )
        .mappings()
        .one_or_none()
    )


def get_profile(
    connection: Connection, actor: ActorContext, subject_id: UUID | None = None
):
    return (
        connection.execute(
            select(
                EmployeeProfile.display_name,
                EmployeeProfile.department,
                EmployeeProfile.employment_start,
            ).where(*self_scope(EmployeeProfile, actor, subject_id))
        )
        .mappings()
        .one_or_none()
    )


def get_history(
    connection: Connection, actor: ActorContext, subject_id: UUID | None = None
):
    return (
        connection.execute(
            select(
                LeaveHistory.id,
                LeaveHistory.event_type,
                LeaveHistory.days_delta,
                LeaveHistory.occurred_at,
            )
            .where(*self_scope(LeaveHistory, actor, subject_id))
            .order_by(
                LeaveHistory.occurred_at,
                LeaveHistory.id,
            )
            .limit(100)
        )
        .mappings()
        .all()
    )


def get_history_page(
    connection: Connection,
    actor: ActorContext,
    limit: int,
    after: tuple[datetime, UUID] | None = None,
):
    if not 1 <= limit <= 100:
        raise ValueError("History limit must be 1-100")
    query = select(
        LeaveHistory.id,
        LeaveHistory.event_type,
        LeaveHistory.days_delta,
        LeaveHistory.occurred_at,
    ).where(*self_scope(LeaveHistory, actor, None))
    if after is not None:
        query = query.where(
            tuple_(LeaveHistory.occurred_at, LeaveHistory.id) < tuple_(*after)
        )
    return (
        connection.execute(
            query.order_by(
                LeaveHistory.occurred_at.desc(),
                LeaveHistory.id.desc(),
            ).limit(limit + 1)
        )
        .mappings()
        .all()
    )


def has_overlapping_request(
    connection: Connection, actor: ActorContext, start: date, end: date
) -> bool:
    return (
        connection.execute(
            select(LeaveRequest.id)
            .where(
                *self_scope(LeaveRequest, actor, None),
                LeaveRequest.status.in_(("booked", "pending")),
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
            .limit(1)
        ).first()
        is not None
    )
