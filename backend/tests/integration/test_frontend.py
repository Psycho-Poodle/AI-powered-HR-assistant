"""Phase 10 browser smoke against a disposable DB, real API and Vite proxy."""

import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select

from app import main
from app.agent.fake_llm import FakeLLM, FakeLLMPause
from app.api.conversations import get_job_engine
from app.api.leave import get_mutation_engine
from app.auth.dependencies import get_db
from app.core.config import AuthSettings, Settings, get_auth_settings
from app.db.models import LeaveBalance, LeaveRequest, Task, TaskMessage
from app.seed.load_seed import seed_id
from app.services.ingestion import index_seed_policies

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def test_browser_workspace(booking_engine, real_embeddings, monkeypatch):
    if not (ROOT / "frontend/node_modules/vite/bin/vite.js").exists():
        pytest.skip("Run npm ci in frontend before the browser smoke test")
    # Mirror the documented setup: index real policies before serving the UI.
    with booking_engine.begin() as connection:
        index_seed_policies(connection, real_embeddings)
    backend_socket = socket.socket()
    backend_socket.bind(("127.0.0.1", 0))
    backend_url = f"http://127.0.0.1:{backend_socket.getsockname()[1]}"
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        frontend_port = port_probe.getsockname()[1]
    origin = f"http://127.0.0.1:{frontend_port}"
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
            database_url=booking_engine.url.set(
                drivername="postgresql"
            ).render_as_string(hide_password=False)
        ),
    )
    app = main.create_app()
    gate = FakeLLMPause()
    app.state.llm_factory = lambda: FakeLLM(gate)

    def db():
        with booking_engine.begin() as c:
            yield c

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_job_engine] = lambda: booking_engine
    app.dependency_overrides[get_mutation_engine] = lambda: booking_engine
    app.dependency_overrides[get_auth_settings] = lambda: settings

    @app.post("/api/v1/_test/release")
    def release():
        gate.release.set()
        return {"released": True}

    @app.get("/api/v1/_test/inspect")
    def inspect():
        # Test-only routes are attached to this ephemeral app, never production.
        with booking_engine.connect() as c:
            task = c.execute(
                select(Task.id).where(
                    Task.original_request == "My remaining leave balance"
                )
            ).scalar_one()
            return {
                "task_id": str(task),
                "notes": c.execute(
                    select(func.count())
                    .select_from(TaskMessage)
                    .where(TaskMessage.task_id == task)
                ).scalar_one(),
                "requests": c.execute(
                    select(func.count()).select_from(LeaveRequest)
                ).scalar_one(),
                "balance": str(
                    c.execute(
                        select(LeaveBalance.days_left).where(
                            LeaveBalance.user_id == seed_id("user", "summit", "maya")
                        )
                    ).scalar_one()
                ),
            }

    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [backend_socket]}, daemon=True
    )
    thread.start()
    env = {**os.environ, "API_PROXY_TARGET": backend_url, "SMOKE_BASE_URL": origin}
    vite = subprocess.Popen(
        [
            "node",
            "node_modules/vite/bin/vite.js",
            "--host",
            "127.0.0.1",
            "--port",
            str(frontend_port),
            "--strictPort",
        ],
        cwd=ROOT / "frontend",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(timeout=1) as client:
            for _ in range(300):
                assert thread.is_alive() and vite.poll() is None
                try:
                    if server.started and client.get(origin).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Frontend/API did not start")
        result = subprocess.run(
            ["node", "tests/smoke.mjs"],
            cwd=ROOT / "frontend",
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(result.stdout)
        assert result.returncode == 0, result.stderr
    finally:
        gate.release.set()
        vite.terminate()
        vite.wait(timeout=10)
        server.should_exit = True
        thread.join(15)
        backend_socket.close()
        assert not thread.is_alive()
