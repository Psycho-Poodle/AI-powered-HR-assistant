"""Bounded owner-only history, reauthorized before every provider context send."""

from pydantic import ValidationError
from sqlalchemy import func, select

from app.agent.state import ExecutionState
from app.agent.tool_registry import filter_policy_results, recheck_actor
from app.db.models import ActionProposal, Task
from app.schemas.workflow import ConversationContext, LeaveWorkflow, Turn


def effective_workflow(connection, task, actor):
    raw = task["plan"].get("execution", {}).get("workflow")
    if not raw:
        return None
    try:
        workflow = LeaveWorkflow.model_validate(raw)
    except ValidationError:
        return None
    if (
        workflow.task_id != task["id"]
        or workflow.revision != task["instruction_revision"]
    ):
        return None
    if task["status"] in {"cancelled", "cancelling", "failed"}:
        return workflow.model_copy(update={"status": "cancelled"})
    proposal = (
        connection.execute(
            select(ActionProposal)
            .where(
                ActionProposal.task_id == task["id"],
                ActionProposal.company_id == actor.company_id,
                ActionProposal.owner_user_id == actor.user_id,
            )
            .order_by(ActionProposal.created_at.desc(), ActionProposal.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if proposal:
        status = "proposed" if proposal["status"] == "pending" else proposal["status"]
        if (
            status == "proposed"
            and proposal["expires_at"]
            <= connection.execute(select(func.clock_timestamp())).scalar_one()
        ):
            status = "expired"
        return workflow.model_copy(
            update={"status": status, "proposal_id": proposal["id"]}
        )
    return workflow


def load_context(engine, row, actor, notes):
    with engine.begin() as c:
        recheck_actor(c, actor)
        previous = (
            c.execute(
                select(Task)
                .where(
                    Task.company_id == actor.company_id,
                    Task.owner_user_id == actor.user_id,
                    Task.conversation_id == row["conversation_id"],
                    Task.id != row["id"],
                    Task.created_at <= row["created_at"],
                )
                .order_by(Task.created_at.desc(), Task.id.desc())
                .limit(4)
            )
            .mappings()
            .all()
        )
        turns, active, seen_origins = [], None, set()
        for task in previous:
            try:
                state = ExecutionState.model_validate(task["plan"]["execution"])
            except (KeyError, ValidationError):
                continue
            permitted = filter_policy_results(c, state.subtasks, actor)
            # Historical rendered answers can contain now-revoked policy text.
            answer = (
                state.answer
                if permitted == state.subtasks
                else "[Prior sources no longer available]"
            )
            user = task["original_request"][:3000]
            if state.instructions:
                user += (
                    "\nAdditional user notes: " + "\n".join(state.instructions)[-1000:]
                )
            turns.append(Turn(user=user, assistant=answer[:1800]))
            workflow = effective_workflow(c, task, actor)
            if workflow and workflow.origin_task_id not in seen_origins:
                seen_origins.add(workflow.origin_task_id)
                if active is None and workflow.status in {
                    "collecting_dates",
                    "ready",
                    "proposed",
                }:
                    active = workflow
        return ConversationContext(
            history=tuple(reversed(turns)), notes=tuple(notes), active_leave=active
        )
