"""Self-only HR results and bounded validation inputs."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEMO_CONVENTION = (
    "FICTIONAL DEMONSTRATION CONVENTION: inclusive Monday-Friday days only; "
    "no verified employer weekends, public holidays, accrual or half-days. "
    "Validation is advisory and saves nothing."
)


class HRModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BalanceResponse(HRModel):
    days_left: Decimal
    as_of: datetime


class ProfileResponse(HRModel):
    display_name: str
    department: str
    employment_start: date


class HistoryItem(HRModel):
    id: UUID
    event_type: str
    days_delta: Decimal
    occurred_at: datetime


class HistoryPage(HRModel):
    items: tuple[HistoryItem, ...]
    next_cursor: str | None


class HistoryQuery(HRModel):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=256)


class LeaveValidationInput(HRModel):
    start_date: date
    end_date: date
    leave_type: Literal["annual"] = "annual"

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        if type(value) is date:
            return value
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        raise ValueError("Use an ISO calendar date YYYY-MM-DD")


class LeaveValidationResult(HRModel):
    valid: bool
    days: Decimal
    available_days: Decimal
    overlaps_existing: bool
    errors: tuple[
        Literal[
            "date_order",
            "range_too_long",
            "no_workdays",
            "overlap",
            "insufficient_balance",
        ],
        ...,
    ]
    convention: str = DEMO_CONVENTION
