"""Atomic Markdown publication and repeatable indexing, without embeddings stubs."""

import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, delete, func, insert, select, update

from app.db.models import Policy, PolicyChunk, User
from app.rag.embeddings import LocalEmbeddings
from app.rag.ingest import CHUNKER_VERSION, chunk_markdown, plain_markdown
from app.security.authorization import ActorContext, policy_scope


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=1024 * 1024)
    source_filename: str = Field(min_length=4, max_length=200)
    version: int = Field(ge=1)
    visibility: Literal["all", "hr", "specific_user"] = "all"
    allowed_user_id: UUID | None = None
    provenance: Literal["assignment", "fictional_demo"] = "fictional_demo"


class IngestConflict(ValueError):
    pass


def _replace_index(connection: Connection, policy, embedder: LocalEmbeddings) -> dict:
    chunks = chunk_markdown(policy["body"], embedder.tokenizer)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "source": policy["source_sha256"],
                "model": embedder.model_id,
                "revision": embedder.revision,
                "chunker": CHUNKER_VERSION,
                "chunks": [c.text for c in chunks],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    stored = connection.execute(
        select(PolicyChunk.chunk_no, PolicyChunk.chunk_text)
        .where(
            PolicyChunk.company_id == policy["company_id"],
            PolicyChunk.policy_id == policy["id"],
        )
        .order_by(PolicyChunk.chunk_no)
    ).all()
    unchanged = (
        policy["index_fingerprint"] == fingerprint
        and stored == [(c.number, c.text) for c in chunks]
        and policy["indexed_model"] == embedder.model_id
        and policy["indexed_revision"] == embedder.revision
        and policy["indexed_chunker"] == CHUNKER_VERSION
        and policy["indexed_source_sha256"] == policy["source_sha256"]
    )
    if unchanged:
        return {
            "id": policy["id"],
            "chunks": len(chunks),
            "changed": False,
            "source_sha256": policy["source_sha256"],
            "model": embedder.model_id,
            "revision": embedder.revision,
        }
    vectors = embedder.encode([c.text for c in chunks])
    connection.execute(
        delete(PolicyChunk).where(
            PolicyChunk.company_id == policy["company_id"],
            PolicyChunk.policy_id == policy["id"],
        )
    )
    connection.execute(
        insert(PolicyChunk.__table__),
        [
            {
                "company_id": policy["company_id"],
                "policy_id": policy["id"],
                "chunk_no": chunk.number,
                "chunk_text": chunk.text,
                "embedding": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )
    connection.execute(
        update(Policy)
        .where(Policy.id == policy["id"], Policy.company_id == policy["company_id"])
        .values(
            indexed_model=embedder.model_id,
            indexed_revision=embedder.revision,
            indexed_chunker=CHUNKER_VERSION,
            indexed_source_sha256=policy["source_sha256"],
            index_fingerprint=fingerprint,
            indexed_at=func.now(),
        )
    )
    return {
        "id": policy["id"],
        "chunks": len(chunks),
        "changed": True,
        "source_sha256": policy["source_sha256"],
        "model": embedder.model_id,
        "revision": embedder.revision,
    }


def _index_locked(connection: Connection, policy, embedder: LocalEmbeddings) -> dict:
    with connection.begin_nested():
        return _replace_index(connection, policy, embedder)


def ingest_markdown(
    connection: Connection,
    actor: ActorContext,
    request: IngestRequest,
    embedder: LocalEmbeddings,
) -> dict:
    if actor.role != "hr":
        raise PermissionError("HR role required")
    if (request.visibility == "specific_user") != (request.allowed_user_id is not None):
        raise ValueError("specific_user visibility requires exactly one allowed user")
    if request.allowed_user_id is not None:
        permitted = connection.execute(
            select(User.id).where(
                User.company_id == actor.company_id,
                User.id == request.allowed_user_id,
                User.active.is_(True),
            )
        ).scalar_one_or_none()
        if permitted is None:
            raise PermissionError("Invalid recipient")
    if (
        Path(request.source_filename).name != request.source_filename
        or "/" in request.source_filename
        or "\\" in request.source_filename
        or not request.source_filename.lower().endswith(".md")
    ):
        raise ValueError("Source must be a Markdown basename")
    if not plain_markdown(request.markdown) or not plain_markdown(request.title):
        raise ValueError("Empty Markdown source")
    if request.provenance == "fictional_demo" and (
        "FICTIONAL DEMONSTRATION DATA" not in request.markdown
        or "FICTIONAL DEMONSTRATION DATA" not in request.title
    ):
        raise ValueError("Fictional policy must be visibly labelled")
    if request.provenance == "assignment":
        # Assignment provenance is reserved for controlled seed files, never uploads.
        raise PermissionError("Assignment provenance is reserved for the seed loader")
    digest = hashlib.sha256(request.markdown.encode("utf-8")).hexdigest()
    lock = int.from_bytes(
        hashlib.sha256(f"{actor.company_id}/{request.slug}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    from sqlalchemy import text

    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    existing = (
        connection.execute(
            select(Policy.__table__)
            .where(
                Policy.company_id == actor.company_id,
                Policy.slug == request.slug,
                Policy.version == request.version,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    values = {
        "title": request.title,
        "body": request.markdown,
        "source_sha256": digest,
        "source_filename": request.source_filename,
        "visibility": request.visibility,
        "allowed_user_id": request.allowed_user_id,
        "provenance": request.provenance,
        "is_demo": True,
    }
    if existing is not None:
        # A caller cannot use idempotent ingestion to read or change a hidden source.
        allowed = connection.execute(
            select(Policy.id).where(
                Policy.id == existing["id"],
                policy_scope(actor),
            )
        ).scalar_one_or_none()
        if allowed is None:
            raise PermissionError("Source unavailable")
        if any(existing[k] != v for k, v in values.items()):
            raise IngestConflict(
                "Policy version already exists with different content or access"
            )
        return _index_locked(connection, existing, embedder)
    highest = connection.execute(
        select(func.max(Policy.version)).where(
            Policy.company_id == actor.company_id,
            Policy.slug == request.slug,
        )
    ).scalar_one_or_none()
    if highest is not None and request.version <= highest:
        raise IngestConflict("New policy versions must increase monotonically")
    # Transaction/savepoint includes draft, embeddings, chunks and publication.
    with connection.begin_nested():
        pid = uuid4()
        connection.execute(
            insert(Policy).values(
                id=pid,
                company_id=actor.company_id,
                slug=request.slug,
                version=request.version,
                status="draft",
                **values,
            )
        )
        policy = (
            connection.execute(
                select(Policy.__table__)
                .where(
                    Policy.id == pid,
                    Policy.company_id == actor.company_id,
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        result = _index_locked(connection, policy, embedder)
        connection.execute(
            update(Policy)
            .where(Policy.id == pid, Policy.company_id == actor.company_id)
            .values(status="published", published_at=func.now())
        )
        connection.execute(
            update(Policy)
            .where(
                Policy.company_id == actor.company_id,
                Policy.slug == request.slug,
                Policy.version < request.version,
                Policy.status == "published",
            )
            .values(status="retired")
        )
    return result


def index_seed_policies(
    connection: Connection, embedder: LocalEmbeddings
) -> list[dict]:
    """Trusted CLI/bootstrap only; not exposed through an API or tool."""
    policies = (
        connection.execute(
            select(Policy.__table__)
            .where(
                Policy.status == "published",
            )
            .order_by(Policy.id)
            .with_for_update()
        )
        .mappings()
        .all()
    )
    return [_index_locked(connection, policy, embedder) for policy in policies]
