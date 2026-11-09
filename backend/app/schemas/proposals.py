"""Owner-confirmed annual-leave proposal contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.hr import HRModel, LeaveValidationInput


class ProposalCreate(LeaveValidationInput):
    task_id: UUID


class ProposalVersion(HRModel):
    expected_version: int = Field(ge=1, le=2147483647, strict=True)


class ProposalPayload(LeaveValidationInput):
    days: Decimal = Field(gt=0)
    calendar: Literal["fictional-mon-fri-v1"] = "fictional-mon-fri-v1"


class ProposalView(HRModel):
    id: UUID
    task_id: UUID
    status: Literal["pending", "confirmed", "cancelled", "expired"]
    version: int
    start_date: date
    end_date: date
    days: Decimal
    expires_at: datetime
    calendar: Literal["fictional-mon-fri-v1"] = "fictional-mon-fri-v1"


class BookingResult(HRModel):
    request_id: UUID
    proposal_id: UUID
    status: Literal["booked"] = "booked"
    remaining_days: Decimal
    proposal_version: int
