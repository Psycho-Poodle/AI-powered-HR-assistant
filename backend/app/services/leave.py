"""Read-only leave validation under an explicit fictional demo calendar."""

import base64
import binascii
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection

from app.repositories import leave as repository
from app.schemas.hr import (
    HistoryItem,
    HistoryPage,
    LeaveValidationInput,
    LeaveValidationResult,
)
from app.security.authorization import ActorContext

MAX_RANGE_DAYS = 366


class HRToolError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require_self(actor: ActorContext, subject_id: UUID | None) -> None:
    if subject_id is not None and subject_id != actor.user_id:
        raise HRToolError("forbidden")


def weekday_days(start: date, end: date) -> int:
    if end < start:
        raise HRToolError("date_order")
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise HRToolError("range_too_long")
    # Bounded iteration avoids overflowing date.max on the last iteration.
    return sum((start + timedelta(days=i)).weekday() < 5 for i in range(span))


def encode_cursor(item: HistoryItem) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps(
                [
                    item.occurred_at.isoformat(),
                    str(item.id),
                ]
            ).encode()
        )
        .decode()
        .rstrip("=")
    )


def decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        if not 1 <= len(cursor) <= 256:
            raise ValueError("Invalid cursor length")
        values = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
            )
        )
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError("Invalid cursor structure")
        if not all(isinstance(value, str) for value in values):
            raise ValueError("Invalid cursor values")
        moment, identifier = datetime.fromisoformat(values[0]), UUID(values[1])
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Cursor timestamp must be timezone-aware")
        return moment, identifier
    except (ValueError, TypeError, binascii.Error, UnicodeError) as error:
        raise HRToolError("invalid_cursor") from error


def history_page(
    connection: Connection, actor: ActorContext, limit: int, cursor: str | None
) -> HistoryPage:
    if not 1 <= limit <= 100:
        raise HRToolError("invalid_limit")
    rows = repository.get_history_page(connection, actor, limit, decode_cursor(cursor))
    items = tuple(HistoryItem.model_validate(dict(row)) for row in rows[:limit])
    return HistoryPage(
        items=items,
        next_cursor=(encode_cursor(items[-1]) if len(rows) > limit else None),
    )


def validate_leave(
    connection: Connection, actor: ActorContext, request: LeaveValidationInput
) -> LeaveValidationResult:
    balance = repository.get_balance(connection, actor)
    if balance is None:
        raise HRToolError("not_found")
    available = balance["days_left"]
    errors = []
    try:
        days = Decimal(weekday_days(request.start_date, request.end_date))
    except HRToolError as error:
        return LeaveValidationResult(
            valid=False,
            days=Decimal(0),
            available_days=available,
            overlaps_existing=False,
            errors=(error.code,),
        )
    if days == 0:
        errors.append("no_workdays")
    overlap = repository.has_overlapping_request(
        connection, actor, request.start_date, request.end_date
    )
    if overlap:
        errors.append("overlap")
    if days > available:
        errors.append("insufficient_balance")
    return LeaveValidationResult(
        valid=not errors,
        days=days,
        available_days=available,
        overlaps_existing=overlap,
        errors=tuple(errors),
    )
