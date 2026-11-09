"""Resolve identities on the server and set transaction-local tenant context."""

import hmac
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Connection, create_engine, select, text
from sqlalchemy.engine import make_url

from app.auth.security import COOKIE_NAME, Session
from app.core.config import AuthSettings, get_auth_settings, get_settings
from app.db.models import Company, User
from app.security.authorization import ActorContext


@lru_cache
def get_engine():
    url = make_url(str(get_settings().database_url)).set(
        drivername="postgresql+psycopg"
    )
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def get_db():
    with get_engine().begin() as connection:
        yield connection


Db = Annotated[Connection, Depends(get_db)]
AuthConfig = Annotated[AuthSettings, Depends(get_auth_settings)]


def reject_query_parameters(request: Request) -> None:
    if request.query_params:
        raise HTTPException(422, "Unexpected query parameters")


def check_origin(request: Request, settings: AuthSettings) -> None:
    if request.headers.get("origin") != str(settings.app_origin).rstrip("/"):
        raise HTTPException(403, "Invalid request origin")


def current_session(request: Request) -> Session:
    session = request.app.state.sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
    if session is None:
        raise HTTPException(401, "Authentication required")
    return session


def get_current_actor(
    request: Request,
    session: Annotated[Session, Depends(current_session)],
    connection: Db,
    settings: AuthConfig,
) -> ActorContext:
    # The session's tenant was derived by login, never supplied by a browser field.
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(session.company_id)},
    )
    user = (
        connection.execute(
            select(User.id, User.company_id, User.role)
            .join(Company, Company.id == User.company_id)
            .where(
                User.id == session.user_id,
                User.company_id == session.company_id,
                User.active.is_(True),
                Company.active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise HTTPException(401, "Authentication required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request, settings)
        csrf = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(csrf.encode(), session.csrf_token.encode()):
            raise HTTPException(403, "Invalid CSRF token")
    return ActorContext(user["id"], user["company_id"], user["role"])


CurrentActor = Annotated[ActorContext, Depends(get_current_actor)]


def require_hr(actor: CurrentActor) -> ActorContext:
    if actor.role != "hr":
        raise HTTPException(403, "Access denied")
    return actor
