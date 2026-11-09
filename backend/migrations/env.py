"""Alembic uses DATABASE_URL or an explicitly supplied connection."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config


def run(connection):
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=str(get_settings().database_url),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    from sqlalchemy.engine import make_url

    url = make_url(str(get_settings().database_url)).set(
        drivername="postgresql+psycopg"
    )
    with create_engine(url, poolclass=NullPool).connect() as connection:
        run(connection)
