"""Bounded DAG waves; independent reads overlap and branch failures stay local."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.agent.checkpoints import operation_key
from app.agent.llm_protocol import LLM
from app.agent.planner import plan_request
from app.agent.state import (
    ClarifyStep,
    ExecutionState,
    PlanStep,
    RefuseStep,
    SubtaskResult,
    TalkStep,
    TraceEntry,
)
from app.security.authorization import ActorContext
from app.services.leave import HRToolError


class ReadTools(Protocol):
    async def run(self, step: PlanStep, actor: ActorContext): ...

    async def authorize(
        self, results: tuple[SubtaskResult, ...], actor: ActorContext
    ): ...


async def execute(
    task_id: UUID,
    original_request: str,
    actor: ActorContext,
    llm: LLM,
    tools: ReadTools,
    *,
    username: str,
    company_slug: str,
    companies: tuple[str, ...],
    persist: Callable[[ExecutionState], Awaitable[None]] | None = None,
    plan_override=None,
    cache=None,
    revision: int = 0,
    instructions: tuple[str, ...] = (),
    prior_trace: tuple = (),
) -> ExecutionState:
    state = ExecutionState(
        task_id=task_id,
        original_request=original_request,
        revision=revision,
        instructions=instructions,
    )
    try:
        plan = plan_override or await plan_request(
            llm,
            original_request,
            username=username,
            company_slug=company_slug,
            companies=companies,
        )
    except Exception:
        state = state.model_copy(
            update={"status": "failed", "outcome": "failed", "error": "planning_failed"}
        )
        if persist:
            await persist(state)
        return state
    results = {
        s.id: SubtaskResult(id=s.id, tool=s.tool, status="pending") for s in plan.steps
    }
    for step in plan.steps:
        if cache and operation_key(step) in cache:
            results[step.id] = SubtaskResult.model_validate(
                cache[operation_key(step)]
            ).model_copy(update={"id": step.id})
    trace = list(prior_trace)
    current_keys = {operation_key(s) for s in plan.steps}
    retained = tuple(
        SubtaskResult.model_validate(value)
        for key, value in (cache or {}).items()
        if key not in current_keys
    )
    lock = asyncio.Lock()

    def snapshot(**updates):
        return ExecutionState(
            task_id=task_id,
            original_request=original_request,
            plan=plan,
            subtasks=tuple(results[s.id] for s in plan.steps),
            trace=tuple(trace),
            revision=revision,
            instructions=instructions,
            retained_results=retained,
            **updates,
        )

    async def publish():
        if persist:
            async with lock:
                await persist(snapshot())

    def record(result):
        result = result.model_copy(update={"instruction_revision": revision})
        results[result.id] = result
        trace.append(
            TraceEntry(
                subtask_id=result.id,
                tool=result.tool,
                status=result.status,
                instruction_revision=revision,
            )
        )

    async def run(step):
        record(SubtaskResult(id=step.id, tool=step.tool, status="running"))
        await publish()
        try:
            if isinstance(step, (ClarifyStep, RefuseStep, TalkStep)):
                status = (
                    "clarification"
                    if isinstance(step, ClarifyStep)
                    else ("refused" if isinstance(step, RefuseStep) else "completed")
                )
                result = SubtaskResult(
                    id=step.id, tool=step.tool, status=status, message=step.args.message
                )
            else:
                data = await tools.run(step, actor)
                result = SubtaskResult(
                    id=step.id, tool=step.tool, status="completed", data=data
                )
        except HRToolError as error:
            code = (
                error.code
                if error.code
                in {"forbidden", "not_found", "invalid_cursor", "invalid_limit"}
                else "invalid_input"
            )
            result = SubtaskResult(
                id=step.id, tool=step.tool, status="failed", error=code
            )
        except Exception:
            result = SubtaskResult(
                id=step.id, tool=step.tool, status="failed", error="tool_failed"
            )
        record(result)
        await publish()

    await publish()
    pending = [s for s in plan.steps if results[s.id].status == "pending"]
    while pending:
        ready = [
            s
            for s in pending
            if all(
                results[d].status not in {"pending", "running"} for d in s.depends_on
            )
        ]
        runnable = []
        for step in ready:
            pending.remove(step)
            if any(results[d].status != "completed" for d in step.depends_on):
                record(
                    SubtaskResult(
                        id=step.id,
                        tool=step.tool,
                        status="skipped",
                        error="dependency_failed",
                    )
                )
            else:
                runnable.append(step)
        await publish()
        wave = [asyncio.create_task(run(s)) for s in runnable]
        try:
            await asyncio.gather(*wave)
        except BaseException:
            for child in wave:
                child.cancel()
            await asyncio.gather(*wave, return_exceptions=True)
            raise
    try:
        authorized = await tools.authorize(
            tuple(results[s.id] for s in plan.steps), actor
        )
        results.update({result.id: result for result in authorized})
    except Exception:
        for step in plan.steps:
            record(
                SubtaskResult(
                    id=step.id,
                    tool=step.tool,
                    status="failed",
                    error="authorization_changed",
                )
            )
        final = snapshot(
            status="failed", outcome="failed", error="authorization_changed"
        )
        if persist:
            await persist(final)
        return final
    statuses = {r.status for r in results.values()}
    outcome = (
        "failed"
        if statuses <= {"failed", "skipped"}
        else (
            "partial"
            if statuses & {"failed", "skipped"}
            else (
                "needs_clarification"
                if "clarification" in statuses
                else ("refused" if "refused" in statuses else "completed")
            )
        )
    )
    final = snapshot(
        status="failed" if outcome == "failed" else "completed", outcome=outcome
    )
    await publish()
    try:
        answer = await llm.compose(original_request, final.subtasks)
        if not isinstance(answer, str) or len(answer) > 20000:
            raise ValueError("Invalid composition")
        final = final.model_copy(update={"answer": answer})
    except Exception:
        final = final.model_copy(
            update={
                "status": "failed",
                "outcome": "partial",
                "error": "composition_failed",
            }
        )
    if persist:
        await persist(final)
    return final
