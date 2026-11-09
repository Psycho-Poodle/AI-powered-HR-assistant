"""Trusted administrative CLI for indexing existing published policy sources."""

import json

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.rag.embeddings import get_embeddings
from app.services.ingestion import index_seed_policies


def main():
    engine = create_engine(
        make_url(str(get_settings().database_url)).set(drivername="postgresql+psycopg")
    )
    try:
        with engine.begin() as connection:
            result = index_seed_policies(connection, get_embeddings())
        print(
            json.dumps(
                {
                    "policies": len(result),
                    "changed": sum(r["changed"] for r in result),
                    "chunks": sum(r["chunks"] for r in result),
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
