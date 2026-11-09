"""Migration tests run only in an explicitly identified disposable database."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.db.base import Base
from app.seed.load_seed import DEFAULT_SEED_DIR, load_seed


@pytest.fixture(scope="session")
def migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    disposable = os.environ.get("PHASE2_DISPOSABLE_DATABASE", "")
    if not url or not disposable:
        pytest.skip("Run scripts/verify_phase2.py for isolated migration/seed tests")
    parsed = make_url(url)
    assert disposable.startswith("phase2_") and parsed.database == disposable
    engine = create_engine(
        parsed.set(drivername="postgresql+psycopg"), poolclass=NullPool
    )
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT current_database()")).scalar()
                == disposable
            )
            cluster = str(
                connection.execute(
                    text("SELECT system_identifier FROM pg_control_system()")
                ).scalar()
            )
            assert cluster != os.environ["DEV_CLUSTER_IDENTIFIER"]
            assert inspect(connection).get_table_names() == []
            connection.rollback()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                compare_metadata(MigrationContext.configure(connection), Base.metadata)
                == []
            )
        print("migrations: empty DB -> head; model/schema match")
        yield engine
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            command.upgrade(config, "head")
        print("migrations: head -> base -> head passed")
        engine.dispose()


@pytest.fixture
def db(migrated_engine):
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def seeded(db):
    load_seed(db, DEFAULT_SEED_DIR, "ephemeral-test-password")
    return db


@pytest.fixture(scope="session")
def real_embeddings():
    from app.rag.embeddings import get_embeddings

    return get_embeddings()


@pytest.fixture
def indexed(seeded, real_embeddings):
    from app.services.ingestion import index_seed_policies

    index_seed_policies(seeded, real_embeddings)
    return seeded


@pytest.fixture
def booking_engine(migrated_engine):
    """Separate per-test DB: append-only booking/audit rows are never deleted."""
    from uuid import uuid4

    from sqlalchemy import insert

    from app.db.models import Conversation, Task
    from app.seed.load_seed import seed_id

    assert migrated_engine.url.database == os.environ["PHASE2_DISPOSABLE_DATABASE"]
    name = "phase7_" + uuid4().hex
    engine = create_engine(migrated_engine.url.set(database=name), poolclass=NullPool)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with migrated_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as admin:
        admin.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            load_seed(connection, DEFAULT_SEED_DIR, "ephemeral-test-password")
            for person, company in (
                ("maya", "summit"),
                ("leila", "summit"),
                ("ravi", "pebble"),
            ):
                conversation = seed_id("proposal-test-conversation", person)
                connection.execute(
                    insert(Conversation).values(
                        id=conversation,
                        company_id=seed_id("company", company),
                        owner_user_id=seed_id("user", company, person),
                        title="Fictional proposal test",
                    )
                )
                connection.execute(
                    insert(Task).values(
                        id=seed_id("proposal-test-task", person),
                        company_id=seed_id("company", company),
                        owner_user_id=seed_id("user", company, person),
                        conversation_id=conversation,
                        original_request="Fictional proposal test",
                        status="completed",
                    )
                )
        yield engine
    finally:
        engine.dispose()
        assert name.startswith("phase7_") and engine.url.database == name
        with migrated_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as admin:
            admin.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
