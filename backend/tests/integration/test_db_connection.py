"""Read-only verification of two real, independently initialized clusters."""

import os

import psycopg
import pytest

from app.db.session import check_database

pytestmark = pytest.mark.integration


def test_vector_extension_and_cluster_isolation() -> None:
    dev_url = os.environ.get("DEV_DATABASE_URL")
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not dev_url or not test_url:
        pytest.skip(
            "Set DEV_DATABASE_URL and TEST_DATABASE_URL for live database checks"
        )

    assert dev_url != test_url, "Test connection must not point to development"
    identities = []
    for url in (dev_url, test_url):
        version = check_database(url)
        assert version
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_database(), current_user, system_identifier::text "
                    "FROM pg_control_system()"
                )
                identities.append(cursor.fetchone())
                cursor.execute("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector")
                assert cursor.fetchone()[0] == pytest.approx(1.0)

    dev, test = identities
    assert dev[0] != test[0], "Database names must differ"
    assert dev[1] != test[1], "Database users must differ"
    assert dev[2] != test[2], "Dev/test must have separate PostgreSQL data clusters"
    print(
        f"vector installed and cosine query passed on both; "
        f"dev={dev[0]}/{dev[1]}, test={test[0]}/{test[1]}; "
        "distinct cluster identifiers"
    )
