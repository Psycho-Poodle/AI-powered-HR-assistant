"""Build and restart a uniquely named disposable Compose stack, never dev volumes."""

import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main():
    project = "phase11_" + uuid4().hex
    origin = f"http://127.0.0.1:{port()}"
    password, session_secret = secrets.token_hex(20), secrets.token_hex(32)
    seed_password = secrets.token_hex(20)
    canary = "PRIVATE_REQUEST_LOG_CANARY"
    query_canary = "PRIVATE_SEARCH_LOG_CANARY"
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phase11_", dir=ROOT / "tmp") as scratch:
        env_file = Path(scratch) / ".env"
        values = {
            "POSTGRES_PASSWORD": password,
            "TEST_POSTGRES_PASSWORD": secrets.token_hex(20),
            "SESSION_SECRET": session_secret,
            "APP_ORIGIN": origin,
            "SESSION_COOKIE_SECURE": "false",
            "POSTGRES_PORT": port(),
            "TEST_POSTGRES_PORT": port(),
            "API_PORT": port(),
            "FRONTEND_PORT": origin.rsplit(":", 1)[1],
        }
        env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        # Clear inherited project settings: only this generated env file configures the stack.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in values and not k.startswith("COMPOSE_")
        }
        env["DEMO_SEED_PASSWORD"] = seed_password
        base = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / "docker-compose.yml"),
            "--profile",
            "ui",
        ]

        def compose(*args):
            result = subprocess.run(
                [*base, *args],
                check=False,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                # Redact credentials even when a database/network exception prints a URL.
                output = result.stdout + result.stderr
                for secret in (
                    password,
                    seed_password,
                    session_secret,
                    values["TEST_POSTGRES_PASSWORD"],
                ):
                    output = output.replace(str(secret), "[REDACTED]")
                raise RuntimeError(output[-6000:])
            return result.stdout

        try:
            compose("build", "api", "frontend")
            print("Docker: api + frontend images built", flush=True)
            compose("up", "-d", "--wait", "db", "db_test")
            compose("run", "--rm", "api", "alembic", "upgrade", "head")
            compose(
                "run",
                "--rm",
                "-e",
                "DEMO_SEED_PASSWORD",
                "api",
                "python",
                "-m",
                "app.seed.load_seed",
                "--seed-dir",
                "/seed",
            )
            compose("run", "--rm", "api", "python", "-m", "app.rag.index_seed")
            compose("up", "--build", "-d", "--wait")
            print(
                "Docker: clean isolated startup, migrations, seed and real local index passed",
                flush=True,
            )
            with httpx.Client(
                base_url=origin, headers={"Origin": origin}, timeout=20
            ) as client:
                assert client.get("/").status_code == 200
                assert client.get("/api/v1/health/live").json() == {"status": "ok"}

                def login():
                    response = client.post(
                        "/api/v1/auth/login",
                        json={"username": "maya", "password": seed_password},
                    )
                    assert response.status_code == 200
                    return {"X-CSRF-Token": response.json()["csrf_token"]}

                csrf = login()
                conversation = client.post(
                    "/api/v1/conversations", headers=csrf, json={}
                ).json()["id"]
                original = f"My balance and late attendance policy. {canary}"
                task_id = client.post(
                    f"/api/v1/conversations/{conversation}/tasks",
                    headers=csrf,
                    json={"message": original},
                ).json()["task_id"]
                for _ in range(600):
                    task = client.get(f"/api/v1/tasks/{task_id}").json()
                    if task["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.2)
                assert task["status"] == "completed", task["status"]
                state = task["plan"]["execution"]
                # The async task above performs genuine cold model initialization.
                # Audit synchronous search logging after that work, retaining the
                # same HTTP timeout and every retrieval/log-privacy assertion.
                assert (
                    client.get(
                        "/api/v1/policies/search", params={"q": query_canary}
                    ).status_code
                    == 200
                )
                assert (
                    "12.00" in state["answer"] and "one-day pay cut" in state["answer"]
                )
                assert all(
                    s["citation"]["source_filename"].startswith("summit/")
                    for r in state["subtasks"]
                    for s in (r.get("data") or {}).get("sources", [])
                )
                before = client.get(f"/api/v1/tasks/{task_id}/events").text
                assert "task.terminal" in before
                compose("restart", "api", "frontend")
                for _ in range(150):
                    try:
                        if client.get("/api/v1/health/live").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                assert client.get(f"/api/v1/tasks/{task_id}").status_code == 401
                login()
                after = client.get(f"/api/v1/tasks/{task_id}").json()
                assert after["id"] == task_id and after["original_request"] == original
                assert client.get(f"/api/v1/tasks/{task_id}/events").text == before
                csrf = login()
                compose("stop", "db")
                time.sleep(1)
                compose("up", "-d", "--wait", "db")
                recovered = client.post(
                    f"/api/v1/conversations/{conversation}/tasks",
                    headers=csrf,
                    json={"message": "my balance after database recovery"},
                ).json()["task_id"]
                for _ in range(150):
                    recovered_task = client.get(f"/api/v1/tasks/{recovered}").json()
                    if recovered_task["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.2)
                assert recovered_task["status"] == "completed"
                assert "12.00" in recovered_task["plan"]["execution"]["answer"]
                print(
                    "Docker: UI proxy, keyless policy SQL, restart/SSE persistence and real DB-outage recovery passed",
                    flush=True,
                )
            logs = compose("logs", "--no-color", "api", "frontend", "db", "db_test")
            assert all(
                secret not in logs
                for secret in (
                    password,
                    seed_password,
                    session_secret,
                    canary,
                    query_canary,
                )
            )
            print(
                "Docker: logs contain no tested password/session-secret/request canaries",
                flush=True,
            )
            print(
                json.dumps(
                    {
                        "project": project,
                        "result": "passed",
                        "persistent_dev_data": "untouched",
                    }
                ),
                flush=True,
            )
        finally:
            if (
                not project.startswith("phase11_")
                or len(project) != len("phase11_") + 32
            ):
                raise RuntimeError("Unsafe Compose cleanup target")
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
