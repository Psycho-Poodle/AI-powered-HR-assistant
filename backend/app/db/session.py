"""Small connection probe shared by startup and real integration tests."""

import psycopg


def check_database(database_url: str) -> str:
    """Verify connectivity and the installed vector extension without writing."""
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("Database connectivity probe failed")
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Required PostgreSQL vector extension is missing")
            return row[0]
