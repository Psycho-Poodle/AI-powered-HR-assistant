"""Only authenticated database identity creates an actor context."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, or_

from app.db.models import Policy


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: UUID
    company_id: UUID
    role: Literal["employee", "hr"]

    def __post_init__(self):
        if self.role not in {"employee", "hr"}:
            raise ValueError("Unknown actor role")


def policy_scope(actor: ActorContext):
    return and_(
        Policy.company_id == actor.company_id,
        Policy.status == "published",
        or_(
            Policy.visibility == "all",
            and_(Policy.visibility == "hr", actor.role == "hr"),
            and_(
                Policy.visibility == "specific_user",
                Policy.allowed_user_id == actor.user_id,
            ),
        ),
    )
