"""Real committed PostgreSQL work with genuinely overlapping HTTP instructions."""

import asyncio
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from app import main
from app.agent.fake_llm import FakeLLM, FakeLLMPause
from app.agent.task_runner import TaskRunner
from app.api.conversations import get_job_engine
from app.auth.dependencies import get_db
from app.core.config import AuthSettings, Settings, get_auth_settings
from app.db.models import Message, Task, TaskMessage
from app.repositories.tasks import LeaseLost, TaskStore

pytestmark = pytest.mark.integration


@pytest.fixture
def running(booking_engine, monkeypatch):
    engine = booking_engine
    settings = AuthSettings(
        session_secret=secrets.token_hex(32), app_origin="https://testserver"
    )
    monkeypatch.setattr(main, "get_auth_settings", lambda: settings)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            database_url=str(
                engine.url.set(drivername="postgresql").render_as_string(
                    hide_password=False
                )
            )
        ),
    )
    app = main.create_app()
    gate = FakeLLMPause()
    app.state.llm_factory = lambda: FakeLLM(gate)

    def db():
        with engine.begin() as c:
            yield c

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_job_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as client:
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": "ephemeral-test-password"},
        ).json()["csrf_token"]
        yield client, {"X-CSRF-Token": token}, gate, engine


def enqueue(running, original="  My balance\n"):
    client, headers, gate, _ = running
    conversation = client.post(
        "/api/v1/conversations", json={}, headers=headers
    ).json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation}/tasks",
        json={"message": original},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    identifier = response.json()["task_id"]
    assert gate.entered.wait(15), client.get(f"/api/v1/tasks/{identifier}").text
    return identifier


def terminal(client, identifier):
    for _ in range(300):
        row = client.get(f"/api/v1/tasks/{identifier}").json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.05)
    raise AssertionError(row)


def test_true_midrun_note_same_id_and_no_repeated_read(running, monkeypatch):
    from app.agent import tool_registry

    calls = []
    original = tool_registry.get_leave_balance

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(tool_registry, "get_leave_balance", counted)
    client, headers, gate, engine = running
    identifier = enqueue(running)
    assert TaskStore(engine).claim() is None  # A live lease excludes a second worker.
    key = str(uuid4())
    body = {
        "message": "Use plain language",
        "expected_revision": 0,
        "client_note_id": key,
    }
    note = client.post(
        f"/api/v1/tasks/{identifier}/instructions", json=body, headers=headers
    )
    assert note.status_code == 202 and note.json() == {
        "task_id": identifier,
        "revision": 1,
    }
    assert (
        client.post(
            f"/api/v1/tasks/{identifier}/instructions", json=body, headers=headers
        ).json()
        == note.json()
    )
    assert (
        client.post(
            f"/api/v1/tasks/{identifier}/instructions",
            json={**body, "message": "different"},
            headers=headers,
        ).status_code
        == 409
    )
    gate.release.set()
    row = terminal(client, identifier)
    execution = row["plan"]["execution"]
    assert row["id"] == execution["task_id"] == identifier
    assert row["original_request"] == execution["original_request"] == "  My balance\n"
    assert row["instruction_revision"] == execution["revision"] == 1
    assert execution["answer"].startswith("In plain language:")
    assert execution["subtasks"][0]["data"]["days_left"] == "12.00"
    assert len(calls) == 1
    assert "cache" not in row["plan"]
    with engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(TaskMessage)
                .where(TaskMessage.task_id == UUID(identifier))
            ).scalar_one()
            == 1
        )
        conversation_id = c.execute(
            select(Task.conversation_id).where(Task.id == UUID(identifier))
        ).scalar_one()
        assert (
            c.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.sender == "assistant",
                )
            ).scalar_one()
            == 1
        )


def test_revision_race_and_owner_scope(running):
    client, headers, gate, _ = running
    identifier = enqueue(running)

    def note(message):
        return client.post(
            f"/api/v1/tasks/{identifier}/instructions",
            json={"message": message, "expected_revision": 0},
            headers=headers,
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(note, ["Be brief", "Use formal language"])) == [202, 409]
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ravi", "password": "ephemeral-test-password"},
    )
    foreign = {"X-CSRF-Token": response.json()["csrf_token"]}
    for suffix, body in [("instructions", {"message": "forged"}), ("cancel", None)]:
        assert (
            client.post(
                f"/api/v1/tasks/{identifier}/{suffix}", json=body, headers=foreign
            ).status_code
            == 404
        )
    assert client.get(f"/api/v1/tasks/{identifier}").status_code == 404
    gate.release.set()


def test_cancel_while_composition_paused(running):
    client, headers, _, engine = running
    identifier = enqueue(running)
    assert (
        client.post(f"/api/v1/tasks/{identifier}/cancel", headers=headers).status_code
        == 202
    )
    row = terminal(client, identifier)
    assert row["status"] == "cancelled" and row["id"] == identifier
    assert not row["plan"]["execution"]["answer"]
    assert (
        client.post(
            f"/api/v1/tasks/{identifier}/instructions",
            json={"message": "resume"},
            headers=headers,
        ).status_code
        == 409
    )
    with engine.connect() as c:
        task = (
            c.execute(select(Task).where(Task.id == UUID(identifier))).mappings().one()
        )
        assert (
            c.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == task["conversation_id"],
                    Message.sender == "assistant",
                )
            ).scalar_one()
            == 0
        )


def test_restart_fences_old_worker_and_reuses_checkpoints(running, monkeypatch):
    from app.agent import tool_registry

    client, _, gate, engine = running
    calls = []
    original = tool_registry.get_leave_balance

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(tool_registry, "get_leave_balance", counted)
    identifier = enqueue(running)
    client.portal.call(client.app.state.task_runner.stop)
    with engine.begin() as c:
        old_token = c.execute(
            select(Task.lease_owner).where(Task.id == UUID(identifier))
        ).scalar_one()
        c.execute(
            update(Task)
            .where(Task.id == UUID(identifier))
            .values(lease_until=func.clock_timestamp() - text("interval '1 second'"))
        )

    # A separate worker represents a restarted process after the paused worker stops.
    async def recover():
        runner = TaskRunner(engine)
        claim = await asyncio.to_thread(runner.store.claim)
        assert claim[0] == UUID(identifier) and claim[1] != old_token
        with pytest.raises(LeaseLost):
            runner.store.heartbeat(UUID(identifier), old_token)
        await runner.run(*claim)

    asyncio.run(recover())
    gate.release.set()
    row = terminal(client, identifier)
    assert row["status"] == "completed" and row["id"] == identifier
    assert len(calls) == 1
    with engine.connect() as c:
        task = (
            c.execute(select(Task).where(Task.id == UUID(identifier))).mappings().one()
        )
        assert (
            c.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == task["conversation_id"],
                    Message.sender == "assistant",
                )
            ).scalar_one()
            == 1
        )
    assert TaskStore(engine).claim() is None


def test_dates_replan_under_same_id_and_retain_completed_validation(running):
    client, headers, gate, _ = running
    original = "prepare leave request 2027-01-04 through 2027-01-06"
    identifier = enqueue(running, original)
    response = client.post(
        f"/api/v1/tasks/{identifier}/instructions",
        json={"message": "Use 2027-02-01 through 2027-02-03", "expected_revision": 0},
        headers=headers,
    )
    assert response.status_code == 202
    gate.release.set()
    row = terminal(client, identifier)
    state = row["plan"]["execution"]
    assert row["status"] == "completed" and state["task_id"] == identifier
    assert state["original_request"] == original
    assert state["plan"]["steps"][-1]["args"]["start_date"] == "2027-02-01"
    assert state["retained_results"][-1]["tool"] == "validate_leave_request"
    assert state["retained_results"][-1]["status"] == "completed"
    assert state["subtasks"][-1]["instruction_revision"] == 1


def test_notes_and_original_are_database_immutable(running):
    from sqlalchemy.exc import DBAPIError

    client, headers, gate, engine = running
    identifier = enqueue(running)
    assert (
        client.post(
            f"/api/v1/tasks/{identifier}/instructions",
            json={"message": "Be brief"},
            headers=headers,
        ).status_code
        == 202
    )
    with engine.connect() as c:
        with pytest.raises(DBAPIError):
            with c.begin():
                c.execute(
                    update(TaskMessage)
                    .where(TaskMessage.task_id == UUID(identifier))
                    .values(instruction="tampered")
                )
        with pytest.raises(DBAPIError):
            with c.begin():
                c.execute(
                    update(Task)
                    .where(Task.id == UUID(identifier))
                    .values(original_request="tampered")
                )
    gate.release.set()
    assert terminal(client, identifier)["original_request"] == "  My balance\n"
