"""Demo credential login and session revocation."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select

from app.auth.dependencies import (
    AuthConfig,
    CurrentActor,
    Db,
    check_origin,
    reject_query_parameters,
)
from app.auth.security import COOKIE_NAME, COOKIE_PATH, verify_password
from app.db.models import Company, User

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    dependencies=[Depends(reject_query_parameters)],
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    connection: Db,
    settings: AuthConfig,
):
    check_origin(request, settings)
    # Demo usernames must resolve uniquely across active tenants.
    # A browser cannot supply an authoritative tenant selector.
    users = (
        connection.execute(
            select(
                User.id,
                User.company_id,
                User.username,
                User.password_hash,
                User.role,
                Company.slug,
                Company.name,
            )
            .join(Company, Company.id == User.company_id)
            .where(
                User.username == body.username,
                User.active.is_(True),
                Company.active.is_(True),
            )
            .limit(2)
        )
        .mappings()
        .all()
    )
    user = users[0] if len(users) == 1 else None
    if not verify_password(
        user["password_hash"] if user else None, body.password.get_secret_value()
    ):
        raise HTTPException(401, "Invalid credentials")
    request.app.state.sessions.revoke(request.cookies.get(COOKIE_NAME, ""))
    token, session = request.app.state.sessions.create(user["id"], user["company_id"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return {
        "user": {"id": user["id"], "username": user["username"]},
        "company": {
            "id": user["company_id"],
            "slug": user["slug"],
            "name": user["name"],
        },
        "role": user["role"],
        "csrf_token": session.csrf_token,
    }


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, actor: CurrentActor, settings: AuthConfig
):
    if await request.body():
        raise HTTPException(422, "Expected an empty request body")
    request.app.state.sessions.revoke(request.cookies.get(COOKIE_NAME, ""))
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )
