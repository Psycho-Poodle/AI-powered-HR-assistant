"""Typed append-only events; the task row serializes allocation and retries."""

import json
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import func, insert, select

from app.db.models import Task, TaskEvent
from app.repositories.policies import get_policy
from app.tools.policy import PolicyToolResult


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Status(Payload):
    kind: Literal["task.status"] = "task.status"
    status: Literal["queued", "running", "cancelling", "awaiting_confirmation"]


class Updated(Payload):
    kind: Literal["task.updated"] = "task.updated"
    note_accepted: Literal[True] = True


class ToolStatus(Payload):
    kind: Literal["tool.status"] = "tool.status"
    subtask_id: str
    tool: str
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
        "clarification",
        "refused",
        "cancelled",
    ]
    error: str | None = None


class Source(Payload):
    policy_id: UUID
    version: int
    source_sha256: str


class Delta(Payload):
    kind: Literal["assistant.delta"] = "assistant.delta"
    text: str = Field(max_length=512)
    sources: tuple[Source, ...] = ()


class Proposal(Payload):
    kind: Literal["proposal.updated"] = "proposal.updated"
    proposal_id: UUID
    status: Literal["pending", "confirmed", "cancelled", "expired"]
    version: int = Field(ge=1)


class Terminal(Payload):
    kind: Literal["task.terminal"] = "task.terminal"
    status: Literal["completed", "failed", "cancelled"]
    outcome: str | None = None
    error: str | None = None


EventPayload = Annotated[
    Status | Updated | ToolStatus | Delta | Proposal | Terminal,
    Field(discriminator="kind"),
]
PAYLOAD = TypeAdapter(EventPayload)
TERMINAL = {"completed", "failed", "cancelled"}


def append(connection, task_id, revision, key, payload):
    """Append in the caller's transaction. Retry keys are scoped to a task UUID."""
    payload = PAYLOAD.validate_python(payload)
    row = (
        connection.execute(select(Task).where(Task.id == task_id).with_for_update())
        .mappings()
        .one()
    )
    identifier = uuid5(task_id, key)
    stored = {"revision": revision, "data": payload.model_dump(mode="json")}
    prior = (
        connection.execute(
            select(TaskEvent.seq, TaskEvent.payload).where(
                TaskEvent.id == identifier,
                TaskEvent.company_id == row["company_id"],
                TaskEvent.task_id == task_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior is not None:
        if prior["payload"] != stored:
            raise ValueError("Conflicting event retry key")
        return prior["seq"]
    seq = (
        connection.execute(
            select(func.coalesce(func.max(TaskEvent.seq), 0)).where(
                TaskEvent.task_id == task_id, TaskEvent.company_id == row["company_id"]
            )
        ).scalar_one()
        + 1
    )
    connection.execute(
        insert(TaskEvent).values(
            id=identifier,
            company_id=row["company_id"],
            task_id=task_id,
            seq=seq,
            event_type=payload.kind,
            payload=stored,
        )
    )
    return seq


def task_status(connection, row, status, *, outcome=None, error=None):
    revision = row["instruction_revision"]
    payload = (
        Terminal(status=status, outcome=outcome, error=error)
        if status in TERMINAL
        else Status(status=status)
    )
    return append(
        connection, row["id"], revision, f"status:{revision}:{status}", payload
    )


def checkpoint(connection, row, state, terminal):
    # Stable status keys suppress duplicate checkpoints and recovered read retries.
    for result in state.subtasks:
        append(
            connection,
            row["id"],
            state.revision,
            f"tool:{state.revision}:{result.id}:{result.tool}:{result.status}:{result.error}",
            ToolStatus(
                subtask_id=result.id,
                tool=result.tool,
                status=result.status,
                error=result.error,
            ),
        )
    if terminal:
        sources = tuple(
            Source(
                policy_id=s.citation.policy_id,
                version=s.citation.version,
                source_sha256=s.citation.source_sha256,
            )
            for r in state.subtasks
            if isinstance(r.data, PolicyToolResult)
            for s in r.data.sources
        )
        for index in range(0, len(state.answer), 512):
            append(
                connection,
                row["id"],
                state.revision,
                f"delta:{state.revision}:{index}",
                Delta(text=state.answer[index : index + 512], sources=sources),
            )
        task_status(
            connection, row, state.status, outcome=state.outcome, error=state.error
        )


def proposal_changed(connection, row, status=None, version=None):
    append(
        connection,
        row["task_id"],
        connection.execute(
            select(Task.instruction_revision).where(
                Task.id == row["task_id"], Task.company_id == row["company_id"]
            )
        ).scalar_one(),
        f"proposal:{row['id']}:{version or row['version']}",
        Proposal(
            proposal_id=row["id"],
            status=status or row["status"],
            version=version or row["version"],
        ),
    )


def wire(connection, actor, row):
    """Recheck historical provenance before revealing any saved answer fragment."""
    payload = PAYLOAD.validate_python(row["payload"]["data"])
    data = payload.model_dump(mode="json", exclude={"kind", "sources"})
    if isinstance(payload, Delta):
        for source in payload.sources:
            current = get_policy(connection, actor, source.policy_id)
            if (
                current is None
                or current["version"] != source.version
                or current["source_sha256"] != source.source_sha256
            ):
                data = {"text": "", "redacted": True}
                break
    body = {
        "task_id": str(row["task_id"]),
        "seq": row["seq"],
        "revision": row["payload"]["revision"],
        "payload": data,
    }
    encoded = json.dumps(body, ensure_ascii=True)
    return f"id: {row['seq']}\nevent: {payload.kind}\ndata: {encoded}\n\n"
