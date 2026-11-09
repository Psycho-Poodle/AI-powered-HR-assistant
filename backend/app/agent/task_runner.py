"""Durable, bounded read-only runner; leases fence every persisted checkpoint."""

import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.agent.checkpoints import operation_key
from app.agent.executor import execute
from app.agent.fake_llm import FakeLLM
from app.agent.planner import plan_request
from app.agent.state import ExecutionState, Plan, TalkStep, TraceEntry
from app.agent.tool_registry import ToolRegistry, recheck_actor
from app.db.models import Company, User
from app.repositories.tasks import Cancelled, LeaseLost, Replan, TaskStore
from app.security.authorization import ActorContext


async def revised_plan(llm, original, notes, **identity):
    plan = await plan_request(llm, original, **identity)
    steps = list(plan.steps)
    for revision, note in enumerate(notes, 1):
        planning_note = note
        if len(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", note)) == 2 and any(
            s.tool in {"clarify", "validate_leave_request"} for s in steps
        ):
            planning_note = "prepare leave request " + note
        amendment = await plan_request(llm, planning_note, **identity)
        mapping = {
            s.id: next(
                (
                    old.id
                    for old in steps
                    if old.tool == s.tool and s.tool != "search_hr_policy"
                ),
                f"{s.id[:28]}_r{revision}",
            )
            for s in amendment.steps
        }
        if any(s.tool == "validate_leave_request" for s in amendment.steps):
            steps = [s for s in steps if s.tool != "clarify"]
        for step in amendment.steps:
            if isinstance(step, TalkStep):
                continue
            match = next(
                (i for i, old in enumerate(steps) if old.tool == step.tool), None
            )
            if match is not None and step.tool != "search_hr_policy":
                old = steps[match]
                steps[match] = step.model_copy(
                    update={
                        "id": old.id,
                        "depends_on": old.depends_on,
                        "revision": revision if old.args != step.args else old.revision,
                    }
                )
            elif not any(operation_key(old) == operation_key(step) for old in steps):
                steps.append(
                    step.model_copy(
                        update={
                            "id": mapping[step.id],
                            "depends_on": tuple(mapping[d] for d in step.depends_on),
                        }
                    )
                )
    return Plan(steps=tuple(steps))


class TaskRunner:
    def __init__(self, engine, llm_factory=FakeLLM, lease_seconds=30):
        self.engine = engine
        self.store = TaskStore(engine, lease_seconds)
        self.llm_factory = llm_factory
        self.workers = set()
        self.supervisor = None

    async def start(self):
        self.supervisor = asyncio.create_task(self.poll())

    async def stop(self):
        if self.supervisor:
            self.supervisor.cancel()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(
            *(tuple(self.workers) + ((self.supervisor,) if self.supervisor else ())),
            return_exceptions=True,
        )

    async def poll(self):
        while True:
            self.workers = {w for w in self.workers if not w.done()}
            if len(self.workers) < 2:
                try:
                    claim = await asyncio.to_thread(self.store.claim)
                except DBAPIError:
                    # Connection failures must not kill the supervisor or log SQL/PII.
                    logging.getLogger(__name__).warning(
                        "Task queue unavailable; retrying"
                    )
                    await asyncio.sleep(0.5)
                    continue
                if claim:
                    self.workers.add(asyncio.create_task(self.run(*claim)))
            await asyncio.sleep(0.05)

    def identity(self, row):
        with self.engine.begin() as c:
            user = (
                c.execute(
                    select(User.username, User.role, Company.slug)
                    .join(Company, Company.id == User.company_id)
                    .where(
                        User.id == row["owner_user_id"],
                        User.company_id == row["company_id"],
                    )
                )
                .mappings()
                .one()
            )
            actor = ActorContext(row["owner_user_id"], row["company_id"], user["role"])
            recheck_actor(c, actor)
            companies = tuple(c.execute(select(Company.slug)).scalars())
            return actor, dict(
                username=user["username"],
                company_slug=user["slug"],
                companies=companies,
            )

    async def run(self, task_id, token):
        work = asyncio.current_task()

        async def monitor():
            try:
                while True:
                    await asyncio.sleep(min(0.1, self.store.lease_seconds / 3))
                    status = await asyncio.to_thread(
                        self.store.heartbeat, task_id, token
                    )
                    if status == "cancelling":
                        work.cancel()
                        return
            except (LeaseLost, DBAPIError):
                work.cancel()

        heartbeat = asyncio.create_task(monitor())
        try:
            while True:
                row, notes = await asyncio.to_thread(self.store.load, task_id, token)
                if row["status"] == "cancelling":
                    raise Cancelled()
                actor, identity = await asyncio.to_thread(self.identity, row)
                llm = self.llm_factory()
                cache = dict(row["plan"].get("cache", {}))
                plan = await revised_plan(
                    llm, row["original_request"], notes, **identity
                )

                self_engine, current_actor = self.engine, actor

                class Adapter:
                    async def compose(
                        self,
                        original,
                        results,
                        llm=llm,
                        notes=notes,
                        self_engine=self_engine,
                        current_actor=current_actor,
                    ):
                        if getattr(llm, "pause", None):
                            await llm.pause.wait()
                        results = await ToolRegistry(self_engine).authorize(
                            results, current_actor
                        )
                        answer = await llm.compose(original, results)
                        if notes:
                            latest = notes[-1].lower()
                            if "plain" in latest or "simple" in latest:
                                answer = "In plain language: " + answer
                            elif "formal" in latest:
                                answer = "Summary: " + answer
                            elif "brief" in latest:
                                answer = "Brief summary: " + answer
                        return answer

                async def persist(state, cache=cache):
                    if state.plan:
                        for step, result in zip(
                            state.plan.steps, state.subtasks, strict=True
                        ):
                            if result.status == "completed":
                                cache[operation_key(step)] = result.model_dump(
                                    mode="json"
                                )
                    await asyncio.to_thread(
                        self.store.save, task_id, token, state, cache
                    )

                try:
                    await execute(
                        task_id,
                        row["original_request"],
                        actor,
                        Adapter(),
                        ToolRegistry(self.engine),
                        **identity,
                        plan_override=plan,
                        cache=cache,
                        revision=row["instruction_revision"],
                        instructions=notes,
                        prior_trace=tuple(
                            TraceEntry.model_validate(t)
                            for t in row["plan"].get("execution", {}).get("trace", [])
                        ),
                        persist=persist,
                    )
                    return
                except Replan:
                    continue
        except (Cancelled, asyncio.CancelledError):
            # Shutdown preserves leases for restart; explicit cancellation completes it.
            try:
                row, _ = await asyncio.to_thread(self.store.load, task_id, token)
                if row["status"] == "cancelling":
                    await asyncio.to_thread(self.store.cancel_finish, task_id, token)
            except (LeaseLost, DBAPIError):
                pass
        except (LeaseLost, DBAPIError):
            # A DB outage cannot be marked failed durably until DB service returns.
            # Leave the fenced lease for recovery instead of pretending to commit.
            pass
        except Exception:
            try:
                row, notes = await asyncio.to_thread(self.store.load, task_id, token)
                failed = ExecutionState(
                    task_id=task_id,
                    original_request=row["original_request"],
                    revision=row["instruction_revision"],
                    instructions=notes,
                    status="failed",
                    outcome="failed",
                    error="runner_failed",
                )
                if "execution" in row["plan"]:
                    failed = ExecutionState.model_validate(
                        row["plan"]["execution"]
                    ).model_copy(
                        update={
                            "revision": row["instruction_revision"],
                            "instructions": notes,
                            "status": "failed",
                            "outcome": "failed",
                            "answer": "",
                            "error": "runner_failed",
                        }
                    )
                await asyncio.to_thread(
                    self.store.save,
                    task_id,
                    token,
                    failed,
                    row["plan"].get("cache", {}),
                )
            except (LeaseLost, Replan, Cancelled, DBAPIError):
                pass
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
