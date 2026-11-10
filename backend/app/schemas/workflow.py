"""Server-owned workflow state; neither model text nor document text grants it."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "conversation",
    "policy_question",
    "leave_balance",
    "hr_read",
    "leave_initiation",
    "leave_continuation",
    "leave_confirmation",
    "cancellation",
    "clarification",
    "refusal",
]


class LeaveWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["leave_request"] = "leave_request"
    task_id: UUID
    origin_task_id: UUID
    revision: int = Field(ge=0)
    status: Literal[
        "collecting_dates", "ready", "proposed", "confirmed", "cancelled", "expired"
    ]
    start_date: date | None = None
    end_date: date | None = None
    proposal_id: UUID | None = None


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user: str
    assistant: str


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    history: tuple[Turn, ...] = ()
    notes: tuple[str, ...] = ()
    active_leave: LeaveWorkflow | None = None
