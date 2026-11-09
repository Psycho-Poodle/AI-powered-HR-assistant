"""Small Phase 3 reads for demonstrating authorization boundaries."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import CurrentActor, Db, reject_query_parameters
from app.db.models import Company, User
from app.repositories.policies import get_policy

router = APIRouter(prefix="/api/v1", dependencies=[Depends(reject_query_parameters)])


@router.get("/me")
def me(actor: CurrentActor, connection: Db):
    user = (
        connection.execute(
            select(User.username, Company.slug, Company.name)
            .join(Company, Company.id == User.company_id)
            .where(
                User.id == actor.user_id,
                User.company_id == actor.company_id,
            )
        )
        .mappings()
        .one()
    )
    return {
        "id": actor.user_id,
        "username": user["username"],
        "role": actor.role,
        "company": {"id": actor.company_id, "slug": user["slug"], "name": user["name"]},
    }


@router.get("/policies/{policy_id}")
def policy(policy_id: UUID, actor: CurrentActor, connection: Db):
    row = get_policy(connection, actor, policy_id)
    if row is None:
        raise HTTPException(404, "Not found")
    return dict(row)
