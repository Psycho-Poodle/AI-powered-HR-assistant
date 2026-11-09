"""Real embedding inference, real vector SQL and transactional indexing."""

import hashlib

import pytest
from sqlalchemy import event, select, text, update

from app.db.models import Policy
from app.rag.embeddings import MODEL_ID, MODEL_REVISION, EmbeddingUnavailable
from app.rag.search import retrieve
from app.security.authorization import ActorContext
from app.seed.load_seed import seed_id
from app.services.ingestion import (
    IngestConflict,
    IngestRequest,
    index_seed_policies,
    ingest_markdown,
)

pytestmark = pytest.mark.integration


def actor(username="maya"):
    company = "pebble" if username == "ravi" else "summit"
    return ActorContext(
        seed_id("user", company, username),
        seed_id("company", company),
        "hr" if username == "leila" else "employee",
    )


def request(**overrides):
    fields = dict(
        slug="fictional-test",
        version=1,
        title="Leave - FICTIONAL DEMONSTRATION DATA",
        markdown="# FICTIONAL DEMONSTRATION DATA\nFictional annual leave rules.\n",
        source_filename="fictional.md",
    )
    return IngestRequest(**(fields | overrides))


def chunk_snapshot(connection):
    return connection.execute(
        text(
            "SELECT id, policy_id, chunk_no, chunk_text, embedding::text, created_at "
            "FROM policy_chunks ORDER BY id"
        )
    ).all()


def test_repeatable_real_index_with_provenance(seeded, real_embeddings):
    first = index_seed_policies(seeded, real_embeddings)
    assert len(first) == 6 and all(item["changed"] for item in first)
    snapshot = chunk_snapshot(seeded)
    second = index_seed_policies(seeded, real_embeddings)
    assert all(not item["changed"] for item in second)
    assert chunk_snapshot(seeded) == snapshot
    assert seeded.execute(
        text(
            "SELECT count(*) FROM policy_chunks WHERE vector_dims(embedding)=384 "
            "AND vector_norm(embedding) BETWEEN 0.99 AND 1.01"
        )
    ).scalar() == len(snapshot)
    assert seeded.execute(select(Policy.indexed_model).distinct()).scalars().all() == [
        MODEL_ID
    ]
    assert seeded.execute(
        select(Policy.indexed_revision).distinct()
    ).scalars().all() == [MODEL_REVISION]
    print(
        f"real embeddings: {len(snapshot)} normalized vector(384) chunks; "
        "repeat index unchanged"
    )


@pytest.mark.parametrize(
    "username,company,rule",
    [
        ("maya", "summit", "one-day pay cut"),
        ("ravi", "pebble", "warning only"),
    ],
)
def test_real_filtered_cosine_sql(indexed, real_embeddings, username, company, rule):
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(indexed, "before_cursor_execute", capture)
    try:
        sources = retrieve(
            indexed,
            actor(username),
            "What happens if I arrive late three times?",
            real_embeddings,
        )
    finally:
        event.remove(indexed, "before_cursor_execute", capture)
    assert any(rule in source.text for source in sources)
    assert all(
        source.citation.policy_id
        != seed_id(
            "policy", "pebble" if company == "summit" else "summit", "late-arrival", "1"
        )
        for source in sources
    )
    assert any("<=>" in sql and "MATERIALIZED" in sql for sql in statements)
    for source in sources:
        citation = source.citation
        assert (
            citation.reference
            == f"policy:{citation.policy_id}:v{citation.version}:c{citation.chunk_no}"
        )
        assert len(citation.source_sha256) == 64
        assert citation.model == MODEL_ID and citation.revision == MODEL_REVISION


@pytest.mark.parametrize("change", ["draft", "retired", "revision", "source"])
def test_unpublished_or_stale_index_never_retrieved(indexed, real_embeddings, change):
    pid = seed_id("policy", "summit", "late-arrival", "1")
    values = (
        {"status": change}
        if change in {"draft", "retired"}
        else (
            {"indexed_revision": "unverified"}
            if change == "revision"
            else {"indexed_source_sha256": "0" * 64}
        )
    )
    indexed.execute(update(Policy).where(Policy.id == pid).values(**values))
    assert all(
        s.citation.policy_id != pid
        for s in retrieve(
            indexed, actor(), "late arrival", real_embeddings, 20, min_similarity=-1
        )
    )


def test_markdown_ingestion_repeat_conflict_and_new_version(seeded, real_embeddings):
    body = request()
    result = ingest_markdown(seeded, actor("leila"), body, real_embeddings)
    assert result["changed"] and result["chunks"] > 0
    assert result["source_sha256"] == hashlib.sha256(body.markdown.encode()).hexdigest()
    snapshot = chunk_snapshot(seeded)
    repeated = ingest_markdown(seeded, actor("leila"), body, real_embeddings)
    assert not repeated["changed"] and repeated["id"] == result["id"]
    assert chunk_snapshot(seeded) == snapshot
    for changed in (
        request(markdown=body.markdown + "Changed rule"),
        request(visibility="hr"),
    ):
        with pytest.raises(IngestConflict), seeded.begin_nested():
            ingest_markdown(seeded, actor("leila"), changed, real_embeddings)
    newer = ingest_markdown(seeded, actor("leila"), request(version=2), real_embeddings)
    assert newer["id"] != result["id"]
    assert (
        seeded.execute(select(Policy.status).where(Policy.id == result["id"])).scalar()
        == "retired"
    )
    assert (
        seeded.execute(select(Policy.status).where(Policy.id == newer["id"])).scalar()
        == "published"
    )


def test_embedding_failure_does_not_publish_or_leave_partial_rows(
    seeded, real_embeddings, monkeypatch
):
    def fail(texts):
        raise EmbeddingUnavailable("simulated local model failure")

    monkeypatch.setattr(real_embeddings, "encode", fail)
    before = chunk_snapshot(seeded)
    with pytest.raises(EmbeddingUnavailable):
        ingest_markdown(seeded, actor("leila"), request(), real_embeddings)
    assert chunk_snapshot(seeded) == before
    assert (
        seeded.execute(select(Policy.id).where(Policy.slug == "fictional-test")).first()
        is None
    )


def test_permission_recheck_after_ranking(indexed, real_embeddings):
    pid = seed_id("policy", "summit", "late-arrival", "1")
    revoked = []

    def revoke(conn, cursor, statement, parameters, context, executemany):
        if "authorized_chunks AS MATERIALIZED" in statement and not revoked:
            revoked.append(True)
            conn.execute(update(Policy).where(Policy.id == pid).values(visibility="hr"))

    event.listen(indexed, "after_cursor_execute", revoke)
    try:
        sources = retrieve(indexed, actor(), "late attendance", real_embeddings, 20, -1)
    finally:
        event.remove(indexed, "after_cursor_execute", revoke)
    assert revoked and all(source.citation.policy_id != pid for source in sources)
