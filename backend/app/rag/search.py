"""Exact pgvector ranking over a materialized authorized set, then recheck."""

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, select

from app.db.models import Policy, PolicyChunk
from app.rag.embeddings import LocalEmbeddings
from app.rag.ingest import CHUNKER_VERSION, plain_markdown
from app.security.authorization import ActorContext, policy_scope


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)
    reference: str
    policy_id: UUID
    chunk_id: UUID
    version: int
    chunk_no: int
    title: str
    source_filename: str
    source_sha256: str
    provenance: Literal["assignment", "fictional_demo"]
    is_demo: bool
    model: str
    revision: str


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    citation: Citation
    text: str
    similarity: float
    trust: Literal["untrusted_document"] = "untrusted_document"


def index_scope(embedder: LocalEmbeddings):
    return (
        Policy.indexed_model == embedder.model_id,
        Policy.indexed_revision == embedder.revision,
        Policy.indexed_chunker == CHUNKER_VERSION,
        Policy.indexed_source_sha256 == Policy.source_sha256,
        Policy.index_fingerprint.is_not(None),
        Policy.indexed_at.is_not(None),
    )


def retrieve(
    connection: Connection,
    actor: ActorContext,
    query: str,
    embedder: LocalEmbeddings,
    top_k: int = 5,
    min_similarity: float = 0.2,
) -> tuple[Evidence, ...]:
    query = query.strip()
    if not query or len(query) > 1000 or not 1 <= top_k <= 20:
        raise ValueError("Query must be 1-1000 characters and top_k 1-20")
    if not math.isfinite(min_similarity) or not -1 <= min_similarity <= 1:
        raise ValueError("Invalid minimum similarity")
    vector = embedder.encode([query])[0]
    scoped = (
        select(
            PolicyChunk.id.label("chunk_id"),
            PolicyChunk.policy_id,
            PolicyChunk.chunk_no,
            PolicyChunk.chunk_text,
            PolicyChunk.embedding,
        )
        .join(
            Policy,
            (Policy.id == PolicyChunk.policy_id)
            & (Policy.company_id == PolicyChunk.company_id),
        )
        .where(
            PolicyChunk.company_id == actor.company_id,
            policy_scope(actor),
            *index_scope(embedder),
        )
        .cte("authorized_chunks")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    distance = scoped.c.embedding.cosine_distance(vector).label("distance")
    ranked = (
        connection.execute(
            select(
                scoped.c.chunk_id,
                scoped.c.policy_id,
                scoped.c.chunk_no,
                scoped.c.chunk_text,
                distance,
            )
            .order_by(distance, scoped.c.policy_id, scoped.c.chunk_no)
            .limit(top_k)
        )
        .mappings()
        .all()
    )
    evidence = []
    # Hold shared policy locks through transaction end: ACL/status changes cannot
    # race the final context assembly after this independent authorization check.
    for row in ranked:
        if row["distance"] is None or not math.isfinite(row["distance"]):
            continue
        similarity = max(-1.0, min(1.0, 1.0 - row["distance"]))
        if similarity < min_similarity:
            continue
        policy = (
            connection.execute(
                select(
                    Policy.id,
                    Policy.title,
                    Policy.version,
                    Policy.source_filename,
                    Policy.source_sha256,
                    Policy.provenance,
                    Policy.is_demo,
                )
                .where(
                    Policy.id == row["policy_id"],
                    policy_scope(actor),
                    *index_scope(embedder),
                )
                .with_for_update(read=True)
            )
            .mappings()
            .one_or_none()
        )
        if policy is None:
            continue
        citation = Citation(
            reference=f"policy:{policy['id']}:v{policy['version']}:c{row['chunk_no']}",
            policy_id=policy["id"],
            chunk_id=row["chunk_id"],
            version=policy["version"],
            chunk_no=row["chunk_no"],
            title=plain_markdown(policy["title"]),
            source_filename=policy["source_filename"],
            source_sha256=policy["source_sha256"],
            provenance=policy["provenance"],
            is_demo=policy["is_demo"],
            model=embedder.model_id,
            revision=embedder.revision,
        )
        evidence.append(
            Evidence(
                citation=citation,
                text=plain_markdown(row["chunk_text"]),
                similarity=similarity,
            )
        )
    return tuple(evidence)
