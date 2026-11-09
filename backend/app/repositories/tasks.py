"""Owned task mutations and PostgreSQL lease fencing. No business writes."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.state import ExecutionState
from app.db.models import ActionProposal, Message, Task, TaskMessage
from app.stream import events


class Replan(BaseException):
    pass


class LeaseLost(BaseException):
    pass


class Cancelled(BaseException):
    pass


def owned(connection, actor, task_id):
    row = (
        connection.execute(
            select(Task)
            .where(
                Task.id == task_id,
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Not found")
    return row


def invalidate(connection, row):
    changed = (
        connection.execute(
            update(ActionProposal)
            .where(
                ActionProposal.task_id == row["id"],
                ActionProposal.company_id == row["company_id"],
                ActionProposal.owner_user_id == row["owner_user_id"],
                ActionProposal.status == "pending",
            )
            .values(status="cancelled", version=ActionProposal.version + 1)
            .returning(ActionProposal.__table__)
        )
        .mappings()
        .all()
    )
    for proposal in changed:
        events.proposal_changed(connection, proposal)


def append_note(connection, actor, task_id, body):
    row = owned(connection, actor, task_id)
    if body.client_note_id:
        prior = (
            connection.execute(
                select(TaskMessage).where(
                    TaskMessage.task_id == task_id,
                    TaskMessage.client_note_id == body.client_note_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["instruction"] != body.message:
                raise HTTPException(409, "Note key already used")
            return {"task_id": task_id, "revision": prior["revision"]}
    if row["status"] not in {"queued", "running", "awaiting_confirmation"}:
        raise HTTPException(409, "Task is not accepting instructions")
    if (
        body.expected_revision is not None
        and body.expected_revision != row["instruction_revision"]
    ):
        raise HTTPException(409, "Instruction revision changed")
    revision = row["instruction_revision"] + 1
    if revision > 64:
        raise HTTPException(409, "Instruction limit reached")
    connection.execute(
        insert(TaskMessage).values(
            company_id=actor.company_id,
            task_id=task_id,
            user_id=actor.user_id,
            instruction=body.message,
            revision=revision,
            client_note_id=body.client_note_id,
        )
    )
    connection.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(
            instruction_revision=revision,
            status="queued"
            if row["status"] == "awaiting_confirmation"
            else row["status"],
            updated_at=func.clock_timestamp(),
        )
    )
    invalidate(connection, row)
    events.append(connection, task_id, revision, f"note:{revision}", events.Updated())
    return {"task_id": task_id, "revision": revision}


class TaskStore:
    def __init__(self, engine, lease_seconds=30):
        self.engine, self.lease_seconds = engine, lease_seconds

    def claim(self):
        with self.engine.begin() as c:
            row = (
                c.execute(
                    select(Task)
                    .where(
                        Task.status.in_(("queued", "running", "cancelling")),
                        or_(
                            Task.lease_until.is_(None),
                            Task.lease_until <= func.clock_timestamp(),
                        ),
                    )
                    .order_by(Task.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            token = str(uuid4())
            c.execute(
                update(Task)
                .where(Task.id == row["id"])
                .values(
                    lease_owner=token,
                    lease_until=func.clock_timestamp()
                    + timedelta(seconds=self.lease_seconds),
                    status="cancelling" if row["status"] == "cancelling" else "running",
                )
            )
            events.task_status(
                c, row, "cancelling" if row["status"] == "cancelling" else "running"
            )
            return row["id"], token

    def locked(self, c, task_id, token):
        row = (
            c.execute(
                select(Task)
                .where(
                    Task.id == task_id,
                    Task.lease_owner == token,
                    Task.lease_until > func.clock_timestamp(),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LeaseLost()
        if row["lease_until"] <= c.execute(select(func.clock_timestamp())).scalar_one():
            raise LeaseLost()
        return row

    def load(self, task_id, token):
        with self.engine.begin() as c:
            row = self.locked(c, task_id, token)
            notes = tuple(
                c.execute(
                    select(TaskMessage.instruction)
                    .where(
                        TaskMessage.task_id == task_id,
                        TaskMessage.company_id == row["company_id"],
                    )
                    .order_by(TaskMessage.revision)
                ).scalars()
            )
            return dict(row), notes

    def heartbeat(self, task_id, token):
        with self.engine.begin() as c:
            row = self.locked(c, task_id, token)
            c.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    lease_until=func.clock_timestamp()
                    + timedelta(seconds=self.lease_seconds)
                )
            )
            return row["status"]

    def save(self, task_id, token, state, cache):
        signal = None
        with self.engine.begin() as c:
            row = self.locked(c, task_id, token)
            plan = {
                "phase": 8,
                "execution": state.model_dump(mode="json"),
                "cache": cache,
            }
            if row["status"] == "cancelling":
                signal = Cancelled
            elif row["instruction_revision"] != state.revision:
                signal = Replan
            terminal = (
                state.status in {"completed", "failed", "cancelled"} and signal is None
            )
            c.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    plan=plan,
                    updated_at=func.clock_timestamp(),
                    **(
                        {
                            "status": state.status,
                            "lease_owner": None,
                            "lease_until": None,
                        }
                        if terminal
                        else {}
                    ),
                )
            )
            if terminal and state.status != "cancelled":
                c.execute(
                    pg_insert(Message)
                    .values(
                        id=uuid5(NAMESPACE_URL, f"task-answer:{task_id}"),
                        company_id=row["company_id"],
                        conversation_id=row["conversation_id"],
                        sender="assistant",
                        body=state.answer
                        or "Task failed; inspect retained subtask statuses.",
                    )
                    .on_conflict_do_nothing()
                )
            events.checkpoint(c, row, state, terminal)
        if signal:
            raise signal()

    def cancel_finish(self, task_id, token):
        with self.engine.begin() as c:
            row = self.locked(c, task_id, token)
            plan = dict(row["plan"])
            if "execution" in plan:
                state = dict(plan["execution"])
                state.update(status="cancelled", outcome="cancelled", answer="")
                state["revision"] = row["instruction_revision"]
                state["subtasks"] = [
                    {**s, "status": "cancelled"}
                    if s["status"] in {"pending", "running"}
                    else s
                    for s in state.get("subtasks", [])
                ]
                plan["execution"] = state
            else:
                plan["execution"] = ExecutionState(
                    task_id=task_id,
                    original_request=row["original_request"],
                    revision=row["instruction_revision"],
                    status="cancelled",
                    outcome="cancelled",
                ).model_dump(mode="json")
            c.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    status="cancelled",
                    plan=plan,
                    lease_owner=None,
                    lease_until=None,
                    updated_at=func.clock_timestamp(),
                )
            )
            events.checkpoint(
                c, row, ExecutionState.model_validate(plan["execution"]), True
            )
