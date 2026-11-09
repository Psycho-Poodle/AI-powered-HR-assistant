"""Typed self-only SQL tools; no generic SQL, embeddings or booking writes."""

from uuid import UUID

from sqlalchemy import Connection

from app.repositories import leave as repository
from app.schemas.hr import (
    BalanceResponse,
    HistoryPage,
    LeaveValidationInput,
    LeaveValidationResult,
    ProfileResponse,
)
from app.security.authorization import ActorContext
from app.services.leave import HRToolError, history_page, require_self, validate_leave


def get_leave_balance(
    connection: Connection, actor: ActorContext, subject_id: UUID | None = None
) -> BalanceResponse:
    require_self(actor, subject_id)
    row = repository.get_balance(connection, actor, subject_id)
    if row is None:
        raise HRToolError("not_found")
    return BalanceResponse.model_validate(dict(row))


def get_employee_profile(
    connection: Connection, actor: ActorContext, subject_id: UUID | None = None
) -> ProfileResponse:
    require_self(actor, subject_id)
    row = repository.get_profile(connection, actor, subject_id)
    if row is None:
        raise HRToolError("not_found")
    return ProfileResponse.model_validate(dict(row))


def get_leave_history(
    connection: Connection,
    actor: ActorContext,
    *,
    limit: int = 20,
    cursor: str | None = None,
    subject_id: UUID | None = None,
) -> HistoryPage:
    require_self(actor, subject_id)
    return history_page(connection, actor, limit, cursor)


def validate_leave_request(
    connection: Connection,
    actor: ActorContext,
    request: LeaveValidationInput,
    *,
    subject_id: UUID | None = None,
) -> LeaveValidationResult:
    require_self(actor, subject_id)
    return validate_leave(connection, actor, request)
