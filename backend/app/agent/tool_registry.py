"""Closed read-tool dispatch with one SQL connection and actor recheck per call."""

import asyncio
import threading

from sqlalchemy import Engine, select, text

from app.agent.state import (
    BalanceStep,
    HistoryStep,
    PlanStep,
    PolicyStep,
    ProfileStep,
    SubtaskResult,
    ValidationStep,
)
from app.db.models import Company, User
from app.rag.embeddings import get_embeddings
from app.repositories.policies import get_policy
from app.security.authorization import ActorContext
from app.services.leave import HRToolError
from app.tools.leave import (
    get_employee_profile,
    get_leave_balance,
    get_leave_history,
    validate_leave_request,
)
from app.tools.policy import PolicyToolResult, search_hr_policy


def filter_policy_results(connection, results, actor):
    filtered = []
    for result in results:
        if isinstance(result.data, PolicyToolResult):
            permitted = []
            for source in result.data.sources:
                current = get_policy(connection, actor, source.citation.policy_id)
                if (
                    current is not None
                    and current["version"] == source.citation.version
                    and current["source_sha256"] == source.citation.source_sha256
                ):
                    permitted.append(source)
            result = result.model_copy(
                update={
                    "data": PolicyToolResult(
                        status="sources_found" if permitted else "insufficient_sources",
                        sources=tuple(permitted),
                    )
                }
            )
        filtered.append(result)
    return tuple(filtered)


def recheck_actor(connection, actor: ActorContext) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(actor.company_id)},
    )
    role = connection.execute(
        select(User.role)
        .join(Company, Company.id == User.company_id)
        .where(
            User.id == actor.user_id,
            User.company_id == actor.company_id,
            User.active.is_(True),
            Company.active.is_(True),
        )
    ).scalar_one_or_none()
    if role is None or role != actor.role:
        raise HRToolError("forbidden")


class ToolRegistry:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._embedder = None
        self._embedding_lock = threading.Lock()

    async def run(self, step: PlanStep, actor: ActorContext):
        return await asyncio.to_thread(self._run, step, actor)

    async def authorize(self, results: tuple[SubtaskResult, ...], actor: ActorContext):
        def check():
            with self.engine.begin() as connection:
                recheck_actor(connection, actor)
                return filter_policy_results(connection, results, actor)

        return await asyncio.to_thread(check)

    def _run(self, step: PlanStep, actor: ActorContext):
        if isinstance(step, PolicyStep):
            with self._embedding_lock:
                if self._embedder is None:
                    self._embedder = get_embeddings()
        with self.engine.begin() as connection:
            # pgvector retrieval takes shared policy locks for its final recheck;
            # PostgreSQL forbids those locks in a READ ONLY transaction.
            if not isinstance(step, PolicyStep):
                connection.execute(text("SET TRANSACTION READ ONLY"))
            recheck_actor(connection, actor)
            if isinstance(step, BalanceStep):
                return get_leave_balance(connection, actor)
            if isinstance(step, ProfileStep):
                return get_employee_profile(connection, actor)
            if isinstance(step, HistoryStep):
                return get_leave_history(connection, actor, **step.args.model_dump())
            if isinstance(step, ValidationStep):
                return validate_leave_request(connection, actor, step.args)
            if isinstance(step, PolicyStep):
                return search_hr_policy(
                    connection, actor, step.args.query, self._embedder, step.args.top_k
                )
            raise HRToolError("forbidden")
