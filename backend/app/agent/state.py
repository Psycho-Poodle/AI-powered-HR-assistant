"""Validated DAG inputs and immutable execution snapshots."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.hr import (
    BalanceResponse,
    HistoryPage,
    LeaveValidationInput,
    LeaveValidationResult,
    ProfileResponse,
)
from app.schemas.workflow import Intent, LeaveWorkflow
from app.tools.policy import PolicyToolResult


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyArgs(FrozenModel):
    pass


class PolicyArgs(FrozenModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class HistoryArgs(FrozenModel):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=256)


class NoteArgs(FrozenModel):
    message: str = Field(min_length=1, max_length=500)


class Step(FrozenModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    depends_on: tuple[str, ...] = ()
    revision: int = Field(default=0, ge=0)


class BalanceStep(Step):
    tool: Literal["get_leave_balance"] = "get_leave_balance"
    args: EmptyArgs = EmptyArgs()


class ProfileStep(Step):
    tool: Literal["get_employee_profile"] = "get_employee_profile"
    args: EmptyArgs = EmptyArgs()


class HistoryStep(Step):
    tool: Literal["get_leave_history"] = "get_leave_history"
    args: HistoryArgs = HistoryArgs()


class PolicyStep(Step):
    tool: Literal["search_hr_policy"] = "search_hr_policy"
    args: PolicyArgs


class ValidationStep(Step):
    tool: Literal["validate_leave_request"] = "validate_leave_request"
    args: LeaveValidationInput


class ClarifyStep(Step):
    tool: Literal["clarify"] = "clarify"
    args: NoteArgs


class RefuseStep(Step):
    tool: Literal["refuse"] = "refuse"
    args: NoteArgs


class TalkStep(Step):
    tool: Literal["talk"] = "talk"
    args: NoteArgs


PlanStep = Annotated[
    BalanceStep
    | ProfileStep
    | HistoryStep
    | PolicyStep
    | ValidationStep
    | ClarifyStep
    | RefuseStep
    | TalkStep,
    Field(discriminator="tool"),
]


class Plan(FrozenModel):
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=8)
    intents: tuple[Intent, ...] = ()
    leave_evidence: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_dag(self):
        nodes = {step.id: step for step in self.steps}
        if len(nodes) != len(self.steps):
            raise ValueError("Duplicate subtask IDs")
        visited, active = set(), set()

        def visit(identifier):
            if identifier not in nodes or identifier in active:
                raise ValueError("Missing dependency or cyclic plan")
            if identifier in visited:
                return
            active.add(identifier)
            for dependency in nodes[identifier].depends_on:
                visit(dependency)
            active.remove(identifier)
            visited.add(identifier)

        for identifier in nodes:
            visit(identifier)
        return self


StepStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "clarification",
    "refused",
    "cancelled",
]
ToolData = (
    BalanceResponse
    | ProfileResponse
    | HistoryPage
    | LeaveValidationResult
    | PolicyToolResult
)


class SubtaskResult(FrozenModel):
    id: str
    tool: str
    status: StepStatus
    data: ToolData | None = None
    message: str | None = None
    error: str | None = None
    instruction_revision: int = 0


class TraceEntry(FrozenModel):
    subtask_id: str
    tool: str
    status: StepStatus
    instruction_revision: int = 0


class ExecutionState(FrozenModel):
    task_id: UUID
    original_request: str
    plan: Plan | None = None
    status: Literal[
        "queued", "running", "completed", "failed", "cancelling", "cancelled"
    ] = "running"
    outcome: Literal[
        "queued",
        "running",
        "completed",
        "partial",
        "needs_clarification",
        "refused",
        "failed",
        "cancelled",
    ] = "running"
    subtasks: tuple[SubtaskResult, ...] = ()
    trace: tuple[TraceEntry, ...] = ()
    answer: str = ""
    error: str | None = None
    revision: int = 0
    instructions: tuple[str, ...] = ()
    retained_results: tuple[SubtaskResult, ...] = ()
    workflow: LeaveWorkflow | None = None
    provider: str = "fake"
    model: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
