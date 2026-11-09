"""Authenticated SSE reads: no per-subscriber writes or long-lived transactions."""

import asyncio
import re
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text

from app.api.conversations import JobEngine
from app.auth.dependencies import current_session
from app.auth.security import COOKIE_NAME, Session
from app.db.models import Company, Task, TaskEvent, User
from app.security.authorization import ActorContext
from app.stream.events import TERMINAL, wire

router = APIRouter(prefix="/api/v1", tags=["tasks"])
POLL_SECONDS = 0.1
HEARTBEAT_SECONDS = 15.0
BATCH_SIZE = 100


def cursor_value(value):
    if value is None:
        return 0
    if not re.fullmatch(r"[0-9]{1,19}", value) or int(value) > 2**63 - 1:
        raise HTTPException(422, "Invalid event cursor")
    return int(value)


def read_batch(engine, session, task_id, cursor):
    with engine.begin() as c:
        c.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(session.company_id)},
        )
        role = c.execute(
            select(User.role)
            .join(Company, Company.id == User.company_id)
            .where(
                User.id == session.user_id,
                User.company_id == session.company_id,
                User.active.is_(True),
                Company.active.is_(True),
            )
        ).scalar_one_or_none()
        if role is None:
            raise HTTPException(401, "Authentication required")
        actor = ActorContext(session.user_id, session.company_id, role)
        task = c.execute(
            select(Task.status).where(
                Task.id == task_id,
                Task.company_id == actor.company_id,
                Task.owner_user_id == actor.user_id,
            )
        ).one_or_none()
        if task is None:
            raise HTTPException(404, "Not found")
        maximum = c.execute(
            select(func.coalesce(func.max(TaskEvent.seq), 0)).where(
                TaskEvent.task_id == task_id, TaskEvent.company_id == actor.company_id
            )
        ).scalar_one()
        if cursor > maximum:
            raise HTTPException(422, "Event cursor is ahead of this task")
        rows = (
            c.execute(
                select(TaskEvent)
                .where(
                    TaskEvent.task_id == task_id,
                    TaskEvent.company_id == actor.company_id,
                    TaskEvent.seq > cursor,
                    TaskEvent.seq <= maximum,
                )
                .order_by(TaskEvent.seq)
                .limit(BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        frames = [(row["seq"], wire(c, actor, row)) for row in rows]
        return task.status, maximum, frames


async def stream(request, engine, task_id, cursor):
    last_heartbeat = time.monotonic()
    while not await request.is_disconnected():
        session = request.app.state.sessions.resolve(
            request.cookies.get(COOKIE_NAME, "")
        )
        if session is None:
            return  # Never emit private data after logout/expiry.
        try:
            status, maximum, frames = await asyncio.to_thread(
                read_batch, engine, session, task_id, cursor
            )
        except HTTPException:
            return  # Authorization was revoked after the initial HTTP headers.
        for seq, frame in frames:
            if await request.is_disconnected():
                return
            yield frame
            cursor = seq
        if status in TERMINAL and cursor >= maximum:
            return
        if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"  # Comments never consume durable IDs.
            last_heartbeat = time.monotonic()
        if len(frames) < BATCH_SIZE:
            await asyncio.sleep(POLL_SECONDS)


@router.get("/tasks/{task_id}/events")
async def events(
    task_id: UUID,
    request: Request,
    engine: JobEngine,
    session: Annotated[Session, Depends(current_session)],
):
    if (
        set(request.query_params) - {"after"}
        or len(request.query_params.getlist("after")) > 1
    ):
        raise HTTPException(422, "Unexpected query parameters")
    after = cursor_value(request.query_params.get("after"))
    header = request.headers.get("last-event-id")
    cursor = cursor_value(header) if header is not None else after
    status, maximum, _ = await asyncio.to_thread(
        read_batch, engine, session, task_id, cursor
    )
    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    if status in TERMINAL and cursor == maximum:
        return Response(status_code=204, headers=headers)
    return StreamingResponse(
        stream(request, engine, task_id, cursor),
        media_type="text/event-stream",
        headers=headers,
    )
