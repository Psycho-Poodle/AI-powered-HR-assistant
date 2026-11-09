"""Minimal API entry point; liveness requires no external services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from starlette.exceptions import HTTPException

from app.agent.fake_llm import FakeLLM
from app.agent.task_runner import TaskRunner
from app.api import auth, conversations, leave, me, policies, tasks
from app.auth.dependencies import get_engine
from app.auth.security import SessionStore
from app.core.config import get_auth_settings, get_settings
from app.db.session import check_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_database(str(get_settings().database_url))
    settings = get_auth_settings()
    app.state.sessions = SessionStore(
        settings.session_secret.get_secret_value(), settings.session_ttl_seconds
    )
    runner = None
    runner_engine = None
    if getattr(get_settings(), "task_runner_enabled", True):
        override = app.dependency_overrides.get(conversations.get_job_engine)
        runner_engine = (
            override()
            if override
            else create_engine(
                make_url(str(get_settings().database_url)).set(
                    drivername="postgresql+psycopg"
                ),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
        )
        runner = TaskRunner(runner_engine, getattr(app.state, "llm_factory", FakeLLM))
        app.state.task_runner = runner
        await runner.start()
    try:
        yield
    finally:
        if runner:
            await runner.stop()
        if runner_engine and not app.dependency_overrides.get(
            conversations.get_job_engine
        ):
            runner_engine.dispose()
        if get_engine.cache_info().currsize:
            get_engine().dispose()
            get_engine.cache_clear()


def create_app() -> FastAPI:
    application = FastAPI(title="HR Chat Assistant", version="0.1.0", lifespan=lifespan)
    application.include_router(auth.router)
    application.include_router(policies.router)
    application.include_router(me.router)
    application.include_router(leave.router)
    application.include_router(conversations.router)
    application.include_router(tasks.router)

    @application.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        codes = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "invalid_request",
        }
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": codes.get(error.status_code, "request_failed"),
                    "message": error.detail,
                    "request_id": str(uuid4()),
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Do not echo submitted credentials or authority-spoofing inputs in errors.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request",
                    "request_id": str(uuid4()),
                }
            },
        )

    @application.get("/api/v1/health/live", tags=["health"])
    def health_live() -> dict[str, str]:
        """Report process liveness without checking future dependencies."""
        return {"status": "ok"}

    return application


app = create_app()
