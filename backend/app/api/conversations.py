"""Owned durable task queue, instructions and cancellation."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, insert, select, update

from app.agent.state import ExecutionState
from app.agent.tool_registry import filter_policy_results, recheck_actor
from app.auth.dependencies import CurrentActor, Db, get_engine, reject_query_parameters
from app.core.config import get_llm_settings
from app.db.models import ActionProposal, Conversation, Message, Task, TaskMessage
from app.repositories.tasks import append_note, invalidate
from app.repositories.tasks import owned as owned_task
from app.services.proposals import view as proposal_view
from app.services.task_context import effective_workflow
from app.stream import events

router = APIRouter(
    prefix="/api/v1",
    tags=["conversations"],
    dependencies=[Depends(reject_query_parameters)],
)


def get_job_engine() -> Engine:
    return get_engine()


JobEngine = Annotated[Engine, Depends(get_job_engine)]


@router.get("/runtime")
def runtime(actor: CurrentActor):
    settings = get_llm_settings()
    model = getattr(settings, f"{settings.llm_provider}_model", None)
    key = getattr(settings, f"{settings.llm_provider}_api_key", None)
    return {
        "provider": settings.llm_provider,
        "model": model,
        "configured": settings.llm_provider == "fake"
        or bool(key and key.get_secret_value().strip()),
    }


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New conversation", min_length=1, max_length=200)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value  # Preserve the exact original text, including whitespace.


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationInput, actor: CurrentActor, connection: Db):
    identifier = connection.execute(
        insert(Conversation)
        .values(
            company_id=actor.company_id,
            owner_user_id=actor.user_id,
            title=body.title,
        )
        .returning(Conversation.id)
    ).scalar_one()
    return {"id": identifier, "title": body.title}


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: UUID, actor: CurrentActor, connection: Db):
    row = (
        connection.execute(
            select(Conversation.id, Conversation.title).where(
                Conversation.id == conversation_id,
                Conversation.company_id == actor.company_id,
                Conversation.owner_user_id == actor.user_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Not found")
    tasks = (
        connection.execute(
            select(Task.id, Task.status, Task.original_request)
            .where(
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
                Task.conversation_id == conversation_id,
            )
            .order_by(Task.created_at, Task.id)
        )
        .mappings()
        .all()
    )
    return {**dict(row), "tasks": [dict(task) for task in tasks]}


@router.post("/conversations/{conversation_id}/tasks", status_code=202)
def create_task(
    conversation_id: UUID, body: TaskInput, actor: CurrentActor, engine: JobEngine
):
    task_id = uuid4()
    with engine.begin() as connection:
        recheck_actor(connection, actor)
        owned = connection.execute(
            select(Conversation.id)
            .where(
                Conversation.id == conversation_id,
                Conversation.company_id == actor.company_id,
                Conversation.owner_user_id == actor.user_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(404, "Not found")
        active = connection.execute(
            select(Task.id).where(
                Task.conversation_id == conversation_id,
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
                Task.status.in_(
                    ("queued", "running", "cancelling", "awaiting_confirmation")
                ),
            )
        ).first()
        if active:
            raise HTTPException(409, "Conversation already has an active task")
        connection.execute(
            insert(Task).values(
                id=task_id,
                company_id=actor.company_id,
                conversation_id=conversation_id,
                owner_user_id=actor.user_id,
                original_request=body.message,
                status="queued",
                plan={"phase": 8},
            )
        )
        connection.execute(
            insert(Message).values(
                company_id=actor.company_id,
                conversation_id=conversation_id,
                sender="user",
                body=body.message,
            )
        )
        events.task_status(
            connection, {"id": task_id, "instruction_revision": 0}, "queued"
        )
    return {
        "task_id": task_id,
        "status": "queued",
        "revision": 0,
        "events_url": f"/api/v1/tasks/{task_id}/events",
    }


class InstructionInput(TaskInput):
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    client_note_id: UUID | None = None


@router.post("/tasks/{task_id}/instructions", status_code=202)
def instructions(
    task_id: UUID, body: InstructionInput, actor: CurrentActor, engine: JobEngine
):
    with engine.begin() as connection:
        recheck_actor(connection, actor)
        return append_note(connection, actor, task_id, body)


@router.post("/tasks/{task_id}/cancel", status_code=202)
def cancel(task_id: UUID, actor: CurrentActor, engine: JobEngine):
    with engine.begin() as connection:
        recheck_actor(connection, actor)
        row = owned_task(connection, actor, task_id)
        if row["status"] not in {
            "queued",
            "running",
            "awaiting_confirmation",
            "cancelling",
        }:
            raise HTTPException(409, "Task is already terminal")
        invalidate(connection, row)
        connection.execute(
            update(Task).where(Task.id == task_id).values(status="cancelling")
        )
        events.task_status(connection, row, "cancelling")
    return {"task_id": task_id, "status": "cancelling"}


@router.get("/tasks/{task_id}")
def task(task_id: UUID, actor: CurrentActor, connection: Db):
    row = (
        connection.execute(
            select(
                Task.id,
                Task.status,
                Task.original_request,
                Task.plan,
                Task.instruction_revision,
            ).where(
                Task.id == task_id,
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Not found")
    result = dict(row)
    workflow = effective_workflow(connection, row, actor)
    result["workflow"] = workflow.model_dump(mode="json") if workflow else None
    result["proposals"] = [
        proposal_view(p).model_dump(mode="json")
        for p in connection.execute(
            select(ActionProposal)
            .where(
                ActionProposal.task_id == task_id,
                ActionProposal.company_id == actor.company_id,
                ActionProposal.owner_user_id == actor.user_id,
            )
            .order_by(ActionProposal.created_at)
        ).mappings()
    ]
    result["instructions"] = [
        dict(n)
        for n in connection.execute(
            select(
                TaskMessage.revision, TaskMessage.instruction, TaskMessage.created_at
            )
            .where(
                TaskMessage.task_id == task_id,
                TaskMessage.company_id == actor.company_id,
            )
            .order_by(TaskMessage.revision)
        ).mappings()
    ]
    result["plan"] = {k: v for k, v in row["plan"].items() if k != "cache"}
    if "execution" in row["plan"]:
        state = ExecutionState.model_validate(row["plan"]["execution"])
        permitted = filter_policy_results(connection, state.subtasks, actor)
        retained = filter_policy_results(connection, state.retained_results, actor)
        state = state.model_copy(update={"retained_results": retained})
        if permitted != state.subtasks:
            state = state.model_copy(
                update={
                    "subtasks": permitted,
                    "answer": "",
                    "error": "source_access_changed",
                }
            )
        if state.revision != row["instruction_revision"] or row["status"] in {
            "queued",
            "running",
            "cancelling",
        }:
            state = state.model_copy(update={"answer": ""})
        result["plan"]["execution"] = state.model_dump(mode="json")
    return result
