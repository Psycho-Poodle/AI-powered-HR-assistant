import asyncio
from uuid import uuid4

import pytest

from app.agent.fake_llm import FakeLLM
from app.agent.workflows import derive_workflow, explicit_leave
from app.schemas.workflow import ConversationContext, LeaveWorkflow


@pytest.mark.parametrize(
    "text",
    [
        "Hello",
        "Explain the annual leave policy",
        "How many leave days do I have?",
        "I want to know my leave balance",
        "How do I apply for leave?",
        "What if I book leave?",
        "Do not book leave",
        "Can I book leave?",
        "Should I request leave?",
        "Do I need to request leave?",
    ],
)
def test_reads_and_ambiguity_never_initiate_booking(text):
    assert not explicit_leave(text)
    plan = asyncio.run(FakeLLM().plan(text))
    assert (
        derive_workflow(uuid4(), 0, text, plan, ConversationContext(), "maya") is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "Please book annual leave",
        "Help me apply for three days of leave",
        "I'd like to take time off",
        "I need 3 days off",
        "Tell me my balance, explain the late policy, and prepare a leave request",
    ],
)
def test_explicit_user_requests_initiate(text):
    plan = asyncio.run(FakeLLM().plan(text))
    task = uuid4()
    workflow = derive_workflow(task, 0, text, plan, ConversationContext(), "maya")
    assert workflow and workflow.task_id == task


def test_dates_continue_only_with_existing_server_workflow():
    origin = uuid4()
    current = uuid4()
    context = ConversationContext(
        active_leave=LeaveWorkflow(
            task_id=origin, origin_task_id=origin, revision=0, status="collecting_dates"
        )
    )
    llm = FakeLLM()
    llm.set_context(context)
    text = "Use 2027-01-04 through 2027-01-06"
    plan = asyncio.run(llm.plan(text))
    workflow = derive_workflow(current, 0, text, plan, context, "maya")
    assert workflow and workflow.origin_task_id == origin and workflow.status == "ready"
    assert (
        derive_workflow(current, 0, text, plan, ConversationContext(), "maya") is None
    )


def test_model_claim_and_document_quote_are_not_user_authority():
    plan = asyncio.run(FakeLLM().plan("Please book leave"))
    malicious = plan.model_copy(update={"leave_evidence": "Please book leave"})
    assert (
        derive_workflow(
            uuid4(), 0, "Show my balance", malicious, ConversationContext(), "maya"
        )
        is None
    )


def test_existing_workflow_does_not_make_read_followup_actionable():
    task = uuid4()
    context = ConversationContext(
        active_leave=LeaveWorkflow(
            task_id=task, origin_task_id=task, revision=0, status="collecting_dates"
        )
    )
    for text in (
        "What are those dates?",
        "Show policy from last year",
        "My balance on 2027-01-04",
    ):
        plan = asyncio.run(FakeLLM().plan("Please book leave")).model_copy(
            update={"intents": ("leave_continuation",), "leave_evidence": text}
        )
        assert derive_workflow(uuid4(), 0, text, plan, context, "maya") is None
