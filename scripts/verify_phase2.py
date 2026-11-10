"""Run database tests in a disposable DB; never reset configured dev/test data."""

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from psycopg import sql
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


def psql(service: str, user: str, database: str, statement: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            service,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            database,
            "-At",
        ],
        input=statement,
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    if result.returncode:
        # Do not echo SQL input, which can contain temporary passwords.
        raise RuntimeError(f"Database setup failed for {service}: {result.stderr}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-port", type=int, default=5432)
    parser.add_argument("--test-port", type=int, default=5433)
    parser.add_argument("test_paths", nargs="*", help="Optional pytest paths")
    args = parser.parse_args()
    c = dotenv_values(ROOT / ".env")
    endpoints = {
        "db": (c.get("POSTGRES_USER", "hr_dev"), c.get("POSTGRES_DB", "hr_dev")),
        "db_test": (
            c.get("TEST_POSTGRES_USER", "hr_test"),
            c.get("TEST_POSTGRES_DB", "hr_test"),
        ),
    }
    ids = {
        service: psql(
            service, *values, "SELECT system_identifier FROM pg_control_system();"
        )
        for service, values in endpoints.items()
    }
    if ids["db"] == ids["db_test"]:
        raise RuntimeError(
            "Refusing tests: development and test clusters are identical"
        )

    suffix = uuid4().hex
    database = "phase2_" + suffix
    roles = {"db": "phase2_read_" + suffix, "db_test": "phase2_admin_" + suffix}
    passwords = {service: secrets.token_hex(24) for service in roles}
    created_roles = []
    database_created = False
    try:
        for service, role in roles.items():
            options = "SUPERUSER" if service == "db_test" else "NOSUPERUSER"
            statement = (
                sql.SQL("CREATE ROLE {} LOGIN {} PASSWORD {};")
                .format(
                    sql.Identifier(role),
                    sql.SQL(options),
                    sql.Literal(passwords[service]),
                )
                .as_string()
            )
            psql(service, *endpoints[service], statement)
            created_roles.append(service)
            if service == "db":
                psql(
                    service,
                    *endpoints[service],
                    sql.SQL(
                        "GRANT pg_monitor TO {}; ALTER ROLE {} SET "
                        "default_transaction_read_only = on;"
                    )
                    .format(sql.Identifier(role), sql.Identifier(role))
                    .as_string(),
                )
        psql(
            "db_test",
            *endpoints["db_test"],
            sql.SQL("CREATE DATABASE {} OWNER {};")
            .format(sql.Identifier(database), sql.Identifier(roles["db_test"]))
            .as_string(),
        )
        database_created = True
        env = os.environ.copy()
        for service, key, port, db in (
            ("db", "DEV_DATABASE_URL", args.dev_port, endpoints["db"][1]),
            ("db_test", "TEST_DATABASE_URL", args.test_port, database),
        ):
            env[key] = URL.create(
                "postgresql",
                username=roles[service],
                password=passwords[service],
                host="127.0.0.1",
                port=port,
                database=db,
            ).render_as_string(hide_password=False)
        env["PHASE2_DISPOSABLE_DATABASE"] = database
        env["DEV_CLUSTER_IDENTIFIER"] = ids["db"]
        env["HF_HUB_OFFLINE"] = "1"
        # Test-only override: never inherit a developer's live provider choice.
        env["LLM_PROVIDER"] = "fake"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        env.pop("HF_TOKEN", None)
        env.pop("OPENAI_API_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        env.pop("GOOGLE_API_KEY", None)
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "-c",
                "backend/pyproject.toml",
                *(args.test_paths or ["backend/tests"]),
                "-q",
                "-s",
                "-p",
                "no:cacheprovider",
            ],
            cwd=ROOT,
            env=env,
        )
    finally:
        if database_created:
            if not database.startswith("phase2_") or database != "phase2_" + suffix:
                raise RuntimeError("Unsafe disposable database cleanup target")
            psql(
                "db_test",
                *endpoints["db_test"],
                sql.SQL("DROP DATABASE {} WITH (FORCE);")
                .format(sql.Identifier(database))
                .as_string(),
            )
        for service in reversed(created_roles):
            psql(
                service,
                *endpoints[service],
                sql.SQL("DROP ROLE {};")
                .format(sql.Identifier(roles[service]))
                .as_string(),
            )


if __name__ == "__main__":
    raise SystemExit(main())
