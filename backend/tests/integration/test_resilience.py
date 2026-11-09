"""Real connection/asset failures; recovery must preserve task and write safety."""

import asyncio
import socket
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, insert, select

from app.agent.task_runner import TaskRunner
from app.db.models import LeaveBalance, LeaveRequest, Task, TaskEvent
from app.seed.load_seed import seed_id

pytestmark = pytest.mark.integration


def queued(engine, message):
    identifier = uuid4()
    with engine.begin() as c:
        c.execute(
            insert(Task).values(
                id=identifier,
                company_id=seed_id("company", "summit"),
                owner_user_id=seed_id("user", "summit", "maya"),
                conversation_id=seed_id("proposal-test-conversation", "maya"),
                original_request=message,
            )
        )
    return identifier


def row(engine, identifier):
    with engine.connect() as c:
        return c.execute(select(Task).where(Task.id == identifier)).mappings().one()


def test_queue_survives_real_connection_refusal(booking_engine, caplog):
    identifier = queued(booking_engine, "my balance")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))  # No listener: a real refused TCP connection.
        unavailable = create_engine(
            booking_engine.url.set(
                port=reserved.getsockname()[1],
                password="PRIVATE_DATABASE_PASSWORD_CANARY",
            ),
            connect_args={"connect_timeout": 1},
        )

        async def scenario():
            runner = TaskRunner(booking_engine)
            runner.store.engine = unavailable
            try:
                await runner.start()
                await asyncio.sleep(0.3)
                assert not runner.supervisor.done(), (
                    "Database outage killed the queue supervisor"
                )
                runner.store.engine = booking_engine
                for _ in range(150):
                    if row(booking_engine, identifier)["status"] == "completed":
                        break
                    await asyncio.sleep(0.05)
                assert row(booking_engine, identifier)["status"] == "completed"
            finally:
                await runner.stop()

        try:
            asyncio.run(scenario())
        finally:
            unavailable.dispose()
    assert "PRIVATE_DATABASE_PASSWORD_CANARY" not in caplog.text
    assert "postgresql" not in caplog.text


def test_missing_real_embedding_assets_fail_task_without_booking(
    booking_engine, monkeypatch, tmp_path
):
    from app.rag.embeddings import get_embeddings

    identifier = queued(booking_engine, "late attendance policy")
    get_embeddings.cache_clear()
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", str(tmp_path / "missing-model"))

    async def scenario():
        runner = TaskRunner(booking_engine)
        try:
            await runner.start()
            for _ in range(150):
                if row(booking_engine, identifier)["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)
            state = row(booking_engine, identifier)
            assert state["status"] == "failed"
            assert state["plan"]["execution"]["subtasks"][0]["error"] == "tool_failed"
            with booking_engine.connect() as c:
                assert (
                    c.execute(
                        select(func.count()).select_from(LeaveRequest)
                    ).scalar_one()
                    == 0
                )
                assert (
                    str(
                        c.execute(
                            select(LeaveBalance.days_left).where(
                                LeaveBalance.user_id
                                == seed_id("user", "summit", "maya")
                            )
                        ).scalar_one()
                    )
                    == "12.00"
                )
                terminal = c.execute(
                    select(TaskEvent.payload).where(
                        TaskEvent.task_id == identifier,
                        TaskEvent.event_type == "task.terminal",
                    )
                ).scalar_one()
                assert terminal["data"]["status"] == "failed"
        finally:
            await runner.stop()

    try:
        asyncio.run(scenario())
    finally:
        get_embeddings.cache_clear()
