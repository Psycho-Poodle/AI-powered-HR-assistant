"""Validate model plans and apply deterministic server-side target refusals."""

import re

from app.agent.llm_protocol import LLM
from app.agent.state import NoteArgs, Plan, PolicyStep, RefuseStep


async def plan_request(
    llm: LLM,
    original_request: str,
    *,
    username: str,
    company_slug: str,
    companies: tuple[str, ...],
    target_requests: tuple[str, ...] = (),
) -> Plan:
    raw = await llm.plan(original_request)
    plan = Plan.model_validate(raw.model_dump() if isinstance(raw, Plan) else raw)
    targets = "\n".join((original_request, *target_requests))
    foreign_companies = [
        c
        for c in companies
        if c != company_slug and re.search(rf"\b{re.escape(c)}\b", targets, re.I)
    ]
    other_people = [
        name
        for name in ("maya", "leila", "ravi")
        if name != username and re.search(rf"\b{name}\b", targets, re.I)
    ]
    steps = []
    for step in plan.steps:
        if isinstance(step, PolicyStep) and foreign_companies:
            step = RefuseStep(
                id=step.id,
                depends_on=step.depends_on,
                args=NoteArgs(message="Other-company policy access is denied."),
            )
        elif (
            step.tool
            in {
                "get_leave_balance",
                "get_employee_profile",
                "get_leave_history",
                "validate_leave_request",
            }
            and other_people
        ):
            step = RefuseStep(
                id=step.id,
                depends_on=step.depends_on,
                args=NoteArgs(message="Only your own HR records are available."),
            )
        steps.append(step)
    return plan.model_copy(update={"steps": tuple(steps)})
