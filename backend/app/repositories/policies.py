"""Filter before fetching policy text; no vector retrieval in Phase 3."""

from uuid import UUID

from sqlalchemy import Connection, select

from app.db.models import Policy
from app.security.authorization import ActorContext, policy_scope


def get_policy(connection: Connection, actor: ActorContext, policy_id: UUID):
    return (
        connection.execute(
            select(
                Policy.id,
                Policy.title,
                Policy.body,
                Policy.version,
                Policy.source_filename,
                Policy.source_sha256,
                Policy.provenance,
                Policy.is_demo,
            ).where(Policy.id == policy_id, policy_scope(actor))
        )
        .mappings()
        .one_or_none()
    )
