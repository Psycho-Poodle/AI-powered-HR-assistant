"""Conservative intent evidence checks, independent of retrieved references."""

import re
from uuid import UUID

from app.schemas.workflow import ConversationContext, LeaveWorkflow


def explicit_leave(text: str) -> bool:
    # Tutorial/entitlement questions are reads, not application instructions.
    if re.search(
        r"\bhow\s+(?:can|do|should|to)\b|\b(?:policy|entitlement|balance|remaining)\b",
        text,
        re.I,
    ):
        # A multi-intent message can still contain a separate explicit request.
        clauses = re.split(r"[,;\n]|\band\b", text, flags=re.I)
        return any(
            _request(c) and not re.search(r"\bhow\s+(?:can|do|should|to)\b", c, re.I)
            for c in clauses
        )
    return _request(text)


def _request(text):
    if re.search(
        r"\b(?:know|check|view|explain|understand|learn|information|policy|balance|remaining)\b"
        r"|\b(?:what if|what happens|can i|how many|do i|should i|"
        r"when should|would i)\b",
        text,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:book|apply(?:\s+for)?|prepare|schedule|submit|request|take)\b.{0,65}\b(?:leave|time\s+off|vacation|pto|days?\s+off)\b"
            r"|\b(?:i\s+(?:want|need)|i['’]d\s+like|i\s+would\s+like)\b.{0,65}\b(?:leave|time\s+off|vacation|pto|days?\s+off)\b",
            text,
            re.I,
        )
    ) and not bool(
        re.search(
            r"\b(?:don't|do not|never|not)\s+(?:want\s+to\s+)?"
            r"(?:book|apply|prepare|request|take)\b",
            text,
            re.I,
        )
    )


def infer_intents(text, steps):
    intents = []
    for step in steps:
        kind = {
            "get_leave_balance": "leave_balance",
            "search_hr_policy": "policy_question",
            "get_employee_profile": "hr_read",
            "get_leave_history": "hr_read",
            "clarify": "clarification",
            "refuse": "refusal",
            "talk": "conversation",
        }.get(step.tool)
        if kind and kind not in intents:
            intents.append(kind)
    if explicit_leave(text):
        intents.append("leave_initiation")
    if re.search(
        r"\b(?:confirm|approve)\b.{0,35}\b(?:leave|booking|proposal)\b", text, re.I
    ):
        intents.append("leave_confirmation")
    if re.search(r"\bcancel\b", text, re.I):
        intents.append("cancellation")
    return tuple(dict.fromkeys(intents))


def derive_workflow(
    task_id: UUID,
    revision: int,
    original: str,
    plan,
    context: ConversationContext,
    username: str,
) -> LeaveWorkflow | None:
    candidates = (original, *context.notes)
    evidence = plan.leave_evidence
    if evidence and not any(evidence in text for text in candidates):
        return None
    # Authenticated user messages alone may initiate a workflow. RAG/assistant
    # content is deliberately absent from this decision.
    start = any(explicit_leave(text) for text in candidates)
    foreign_target = any(
        re.search(rf"\b{p}\b", "\n".join(candidates), re.I)
        for p in ("maya", "leila", "ravi")
        if p != username
    )
    if foreign_target:
        return None
    continuation = (
        context.active_leave is not None and "leave_continuation" in plan.intents
    )
    if continuation:
        # Read-only follow-ups must not revive an earlier form.
        continuation = any(
            re.search(
                r"\d{4}-\d{2}-\d{2}|^(?:please\s+|yes[, ]+)?"
                r"(?:use|change|make|move|update|those|these|from)\b",
                t,
                re.I,
            )
            and not re.search(
                r"\b(?:balance|policy|how|what|explain|remaining|history)\b", t, re.I
            )
            for t in candidates
        )
    if not ((start and "leave_initiation" in plan.intents) or continuation):
        return None
    if "cancellation" in plan.intents or "leave_confirmation" in plan.intents:
        return None
    dates = next(
        (s.args for s in reversed(plan.steps) if s.tool == "validate_leave_request"),
        None,
    )
    return LeaveWorkflow(
        task_id=task_id,
        origin_task_id=context.active_leave.origin_task_id if continuation else task_id,
        revision=revision,
        status="ready" if dates else "collecting_dates",
        start_date=dates.start_date if dates else None,
        end_date=dates.end_date if dates else None,
    )
