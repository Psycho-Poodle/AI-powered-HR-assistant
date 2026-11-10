"""Real HTTP streaming over sockets and real committed PostgreSQL events."""

import json
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from app import main
from app.agent.fake_llm import FakeLLM, FakeLLMPause
from app.api import tasks
from app.api.conversations import get_job_engine
from app.api.leave import get_mutation_engine
from app.auth.dependencies import get_db
from app.core.config import AuthSettings, Settings, get_auth_settings
from app.db.models import Policy, Task, TaskEvent, User
from app.stream import events

pytestmark = pytest.mark.integration


@pytest.fixture
def live(booking_engine, monkeypatch):
    engine = booking_engine
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    settings = AuthSettings(
        session_secret=secrets.token_hex(32),
        app_origin=origin,
        session_cookie_secure=False,
    )
    monkeypatch.setattr(main, "get_auth_settings", lambda: settings)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            database_url=engine.url.set(drivername="postgresql").render_as_string(
                hide_password=False
            )
        ),
    )
    monkeypatch.setattr(tasks, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(tasks, "POLL_SECONDS", 0.02)
    app = main.create_app()
    gate = FakeLLMPause()
    app.state.llm_factory = lambda: FakeLLM(gate)

    def db():
        with engine.begin() as c:
            yield c

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_job_engine] = lambda: engine
    app.dependency_overrides[get_mutation_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        for _ in range(500):
            if server.started:
                break
            assert thread.is_alive(), "HTTP server failed to start"
            time.sleep(0.01)
        assert server.started
        with httpx.Client(
            base_url=origin, headers={"Origin": origin}, timeout=20
        ) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "maya", "password": "ephemeral-test-password"},
            )
            csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
            yield client, csrf, gate, engine, app
    finally:
        gate.release.set()
        server.should_exit = True
        thread.join(15)
        sock.close()
        assert not thread.is_alive(), "Stream prevented HTTP server shutdown"


def enqueue(live, message="my balance"):
    client, csrf, gate, _, _ = live
    conversation = client.post("/api/v1/conversations", json={}, headers=csrf).json()[
        "id"
    ]
    response = client.post(
        f"/api/v1/conversations/{conversation}/tasks",
        json={"message": message},
        headers=csrf,
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert response.json()["events_url"] == f"/api/v1/tasks/{task_id}/events"
    assert gate.entered.wait(10)
    return task_id


def frames(response):
    frame = {}
    for line in response.iter_lines():
        if not line:
            if frame:
                yield frame
            frame = {}
        elif line.startswith(":"):
            frame["comment"] = line[1:].strip()
        else:
            key, value = line.split(":", 1)
            frame[key] = json.loads(value) if key == "data" else value.strip()


def finished(client, task_id):
    for _ in range(500):
        row = client.get(f"/api/v1/tasks/{task_id}").json()
        if row["status"] in events.TERMINAL:
            return row
        time.sleep(0.02)
    raise AssertionError("Task did not terminate")


def event_rows(engine, task_id):
    with engine.connect() as c:
        return (
            c.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == UUID(str(task_id)))
                .order_by(TaskEvent.seq)
            )
            .mappings()
            .all()
        )


def test_live_heartbeat_note_terminal_and_disconnect(live):
    client, csrf, gate, engine, _ = live
    task_id = enqueue(live)
    url = f"/api/v1/tasks/{task_id}/events"
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
        initial = []
        for frame in frames(response):
            initial.append(frame)
            if "comment" in frame:
                break
        assert initial[-1] == {"comment": "heartbeat"}
        # Closing a subscriber cannot cancel the paused task.
    assert client.get(f"/api/v1/tasks/{task_id}").json()["status"] == "running"
    note = client.post(
        f"/api/v1/tasks/{task_id}/instructions",
        json={"message": "Use plain language", "client_note_id": str(uuid4())},
        headers=csrf,
    )
    assert note.status_code == 202
    gate.release.set()
    row = finished(client, task_id)
    response = client.get(url)
    result = list(frames(response))
    assert result[-1]["event"] == "task.terminal"
    assert result[-1]["data"]["payload"]["status"] == "completed"
    assert any(f.get("event") == "task.updated" for f in result)
    text = "".join(
        f["data"]["payload"]["text"]
        for f in result
        if f.get("event") == "assistant.delta"
    )
    assert text == row["plan"]["execution"]["answer"]
    assert text.startswith("In plain language:")
    ids = [int(f["id"]) for f in result if "id" in f]
    assert ids == list(range(1, len(ids) + 1))
    assert len(event_rows(engine, task_id)) == len(ids)


def test_replay_duplicate_connections_and_cursors(live):
    client, _, gate, engine, _ = live
    task_id = enqueue(live)
    gate.release.set()
    finished(client, task_id)
    url = f"/api/v1/tasks/{task_id}/events"
    first = list(frames(client.get(url)))
    middle = first[len(first) // 2]["id"]
    before = len(event_rows(engine, task_id))
    repeated = list(frames(client.get(url)))
    assert first == repeated
    replay = list(
        frames(client.get(url + "?after=0", headers={"Last-Event-ID": middle}))
    )
    assert replay == [f for f in first if int(f["id"]) > int(middle)]
    assert list(frames(client.get(url + "?after=" + middle))) == replay
    assert (
        client.get(url, headers={"Last-Event-ID": first[-1]["id"]}).status_code == 204
    )
    assert len(event_rows(engine, task_id)) == before
    for value in ("-1", "1.0", "garbage", "9223372036854775808", "999999"):
        assert client.get(url, headers={"Last-Event-ID": value}).status_code == 422
    assert client.get(url + "?after=-1").status_code == 422
    assert client.get(url + "?company_id=pebble").status_code == 422


def test_two_live_subscribers_receive_identical_log(live):
    client, _, gate, engine, _ = live
    task_id = enqueue(live)
    opened = threading.Barrier(3, timeout=10)

    def subscribe():
        with client.stream("GET", f"/api/v1/tasks/{task_id}/events") as response:
            assert response.status_code == 200
            opened.wait()
            return [f for f in frames(response) if "id" in f]

    with ThreadPoolExecutor(2) as pool:
        left, right = pool.submit(subscribe), pool.submit(subscribe)
        opened.wait()
        gate.release.set()
        a, b = left.result(timeout=15), right.result(timeout=15)
    assert a == b
    assert len(a) == len(event_rows(engine, task_id))
    assert sum(f["event"] == "task.terminal" for f in a) == 1


def test_subscription_ownership_and_live_revocation(live):
    client, _, _, engine, app = live
    task_id = enqueue(live)
    url = f"/api/v1/tasks/{task_id}/events"
    with httpx.Client(base_url=str(client.base_url)) as anonymous:
        assert anonymous.get(url).status_code == 401
    with client.stream("GET", url) as response:
        iterator = frames(response)
        assert next(iterator)["event"] == "task.status"
        with engine.begin() as c:
            owner = c.execute(
                select(Task.owner_user_id).where(Task.id == UUID(str(task_id)))
            ).scalar_one()
            c.execute(update(User).where(User.id == owner).values(active=False))
        # A previously-open connection closes without a terminal or private answer.
        assert all(f.get("event") != "assistant.delta" for f in iterator)
    assert client.get(url).status_code == 401
    for username in ("ravi", "leila"):
        client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "ephemeral-test-password"},
        )
        assert client.get(url).status_code == 404
    assert app.state.task_runner is not None


def test_concurrent_append_deduplicates_and_rolls_back(live):
    _, _, _, engine, _ = live
    task_id = UUID(enqueue(live))
    before = len(event_rows(engine, task_id))

    def append():
        with engine.begin() as c:
            return events.append(c, task_id, 0, "retry-test", events.Updated())

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: append(), range(4)))
    assert len(set(results)) == 1
    assert len(event_rows(engine, task_id)) == before + 1
    with pytest.raises(ValueError, match="retry key"):
        with engine.begin() as c:
            events.append(c, task_id, 0, "retry-test", events.Status(status="running"))
    with pytest.raises(RuntimeError):
        with engine.begin() as c:
            events.append(c, task_id, 0, "rolled-back", events.Updated())
            raise RuntimeError("rollback")
    assert len(event_rows(engine, task_id)) == before + 1

    def distinct(index):
        with engine.begin() as c:
            return events.append(c, task_id, 0, f"distinct:{index}", events.Updated())

    with ThreadPoolExecutor(4) as pool:
        sequences = list(pool.map(distinct, range(12)))
    assert sorted(sequences) == list(range(before + 2, before + 14))


@pytest.mark.parametrize(
    "action,expected", [("cancel", "cancelled"), ("fail", "failed")]
)
def test_explicit_failure_and_cancellation_terminal_events(
    live, action, expected, monkeypatch
):
    client, csrf, gate, _, _ = live
    task_id = enqueue(live)
    if action == "cancel":
        assert (
            client.post(f"/api/v1/tasks/{task_id}/cancel", headers=csrf).status_code
            == 202
        )
    else:
        # Composition errors follow the normal runner checkpoint and terminal path.
        async def broken(*args):
            raise ValueError("private error")

        with monkeypatch.context() as edits:
            edits.setattr(FakeLLM, "compose", broken)
            gate.release.set()
            row = finished(client, task_id)
        assert row["status"] == expected
    finished(client, task_id)
    result = list(frames(client.get(f"/api/v1/tasks/{task_id}/events")))
    assert result[-1]["event"] == "task.terminal"
    assert result[-1]["data"]["payload"]["status"] == expected
    assert "private error" not in json.dumps(result)


def test_replay_redacts_revoked_historical_policy_text(live):
    client, _, gate, engine, _ = live
    task_id = enqueue(live)
    with engine.begin() as c:
        company = c.execute(
            select(Task.company_id).where(Task.id == UUID(task_id))
        ).scalar_one()
        policy = (
            c.execute(
                select(Policy)
                .where(Policy.company_id == company, Policy.visibility == "all")
                .limit(1)
            )
            .mappings()
            .one()
        )
        source = events.Source(
            policy_id=policy["id"],
            version=policy["version"],
            source_sha256=policy["source_sha256"],
        )
        events.append(
            c,
            UUID(task_id),
            0,
            "historic-policy-delta",
            events.Delta(text="REVOKED PRIVATE TEXT", sources=(source,)),
        )
        c.execute(
            update(Policy).where(Policy.id == policy["id"]).values(status="retired")
        )
    gate.release.set()
    finished(client, task_id)
    response = client.get(f"/api/v1/tasks/{task_id}/events")
    assert "REVOKED PRIVATE TEXT" not in response.text
    assert any(
        f.get("data", {}).get("payload", {}).get("redacted") for f in frames(response)
    )


def test_replay_drains_more_than_one_batch(live):
    client, _, gate, engine, _ = live
    task_id = enqueue(live)
    with engine.begin() as c:
        for index in range(tasks.BATCH_SIZE * 2 + 3):
            events.append(c, UUID(task_id), 0, f"batch:{index}", events.Updated())
    gate.release.set()
    finished(client, task_id)
    result = [
        f for f in frames(client.get(f"/api/v1/tasks/{task_id}/events")) if "id" in f
    ]
    assert [int(f["id"]) for f in result] == list(range(1, len(result) + 1))
    assert len(result) == len(event_rows(engine, task_id))
    assert result[-1]["event"] == "task.terminal"


def test_logout_ends_live_subscription(live):
    client, csrf, _, _, _ = live
    task_id = enqueue(live)
    url = f"/api/v1/tasks/{task_id}/events"
    with client.stream("GET", url) as response:
        iterator = frames(response)
        assert next(iterator)["event"] == "task.status"
        assert client.post("/api/v1/auth/logout", headers=csrf).status_code == 204
        assert all(f.get("event") != "assistant.delta" for f in iterator)
    assert client.get(url).status_code == 401


def test_migration_baselines_existing_tasks_without_deleting_logs(booking_engine):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with booking_engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0004_note_replay")
        command.upgrade(config, "head")
        rows = c.execute(select(TaskEvent)).mappings().all()
        assert len(rows) == 3
        assert all(r["seq"] == 1 and r["event_type"] == "task.terminal" for r in rows)
        for row in rows:
            assert (
                events.PAYLOAD.validate_python(row["payload"]["data"]).status
                == "completed"
            )
        command.downgrade(config, "0004_note_replay")
        command.upgrade(config, "head")
        assert c.execute(
            select(TaskEvent.id).order_by(TaskEvent.id)
        ).scalars().all() == sorted(r["id"] for r in rows)


def test_proposal_events_replay_after_execution_without_duplicate_writes(live):
    client, csrf, gate, engine, _ = live
    task_id = enqueue(live, "Prepare a leave request")
    gate.release.set()
    finished(client, task_id)
    cursor = event_rows(engine, task_id)[-1]["seq"]
    body = {"task_id": task_id, "start_date": "2027-01-04", "end_date": "2027-01-06"}
    response = client.post("/api/v1/leave/proposals", json=body, headers=csrf)
    assert response.status_code == 201, response.text
    proposal = response.json()
    assert (
        client.post("/api/v1/leave/proposals", json=body, headers=csrf).json()
        == proposal
    )
    url = f"/api/v1/tasks/{task_id}/events"
    created = list(frames(client.get(url, headers={"Last-Event-ID": str(cursor)})))
    assert len(created) == 1
    assert created[0]["event"] == "proposal.updated"
    assert created[0]["data"]["payload"]["status"] == "pending"
    confirm_url = f"/api/v1/leave/proposals/{proposal['id']}/confirm"
    assert (
        client.post(confirm_url, json={"expected_version": 1}, headers=csrf).status_code
        == 200
    )
    count = len(event_rows(engine, task_id))
    assert (
        client.post(confirm_url, json={"expected_version": 1}, headers=csrf).status_code
        == 409
    )
    confirmed = list(
        frames(client.get(url, headers={"Last-Event-ID": created[0]["id"]}))
    )
    assert (
        len(confirmed) == 1 and confirmed[0]["data"]["payload"]["status"] == "confirmed"
    )
    assert len(event_rows(engine, task_id)) == count
