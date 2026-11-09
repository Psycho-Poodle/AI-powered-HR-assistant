"""Deterministic intent parsing, closed plan schema and real async scheduling."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.executor import execute
from app.agent.fake_llm import FakeLLM
from app.agent.planner import plan_request
from app.agent.state import BalanceStep, Plan, ProfileStep
from app.schemas.hr import BalanceResponse, ProfileResponse
from app.security.authorization import ActorContext


def run(coroutine):
    return asyncio.run(coroutine)


def test_fake_plan_is_deterministic_and_preserves_three_intents():
    text = (
        "Tell me my remaining leaves, explain the late policy, "
        "and prepare a leave request for three days."
    )
    first = run(FakeLLM().plan(text))
    assert first == run(FakeLLM().plan(text))
    assert [step.tool for step in first.steps] == [
        "get_leave_balance",
        "search_hr_policy",
        "clarify",
    ]


def test_dated_leave_depends_on_balance():
    plan = run(FakeLLM().plan("Prepare leave from 2026-11-09 to 2026-11-11"))
    assert plan.steps[-1].tool == "validate_leave_request"
    assert plan.steps[-1].depends_on == ("balance",)


@pytest.mark.parametrize(
    "steps",
    [
        [{"id": "x", "tool": "confirm_leave"}],
        [{"id": "x", "tool": "get_leave_balance", "args": {"company_id": "pebble"}}],
        [{"id": "x", "tool": "get_leave_balance", "depends_on": ["missing"]}],
        [{"id": "x", "tool": "get_leave_balance", "depends_on": ["x"]}],
        [
            {"id": "x", "tool": "get_leave_balance"},
            {"id": "x", "tool": "get_employee_profile"},
        ],
        [
            {"id": "x", "tool": "get_leave_balance", "depends_on": ["y"]},
            {"id": "y", "tool": "get_employee_profile", "depends_on": ["x"]},
        ],
    ],
)
def test_invalid_or_mutating_plan_is_rejected(steps):
    with pytest.raises(ValidationError):
        Plan.model_validate({"steps": steps})


def test_foreign_policy_refusal_does_not_discard_own_balance():
    plan = run(
        plan_request(
            FakeLLM(),
            "My remaining balance and the Pebble handbook",
            username="maya",
            company_slug="summit",
            companies=("summit", "pebble"),
        )
    )
    assert [step.tool for step in plan.steps] == ["get_leave_balance", "refuse"]


class TwoReads(FakeLLM):
    async def plan(self, original_request):
        return Plan(steps=(BalanceStep(id="balance"), ProfileStep(id="profile")))


class GatedReads:
    def __init__(self):
        self.started = set()
        self.both_started = asyncio.Event()

    async def run(self, step, actor):
        self.started.add(step.id)
        if len(self.started) == 2:
            self.both_started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=2)
        if step.id == "balance":
            return BalanceResponse(days_left=Decimal(12), as_of=datetime.now(UTC))
        return ProfileResponse(
            display_name="Fictional", department="Demo", employment_start="2026-01-01"
        )

    async def authorize(self, results, actor):
        return results


def test_independent_steps_reach_gate_concurrently_and_keep_original():
    async def check():
        tools = GatedReads()
        original = "  Preserve this exact original request.\n"
        result = await execute(
            uuid4(),
            original,
            ActorContext(uuid4(), uuid4(), "employee"),
            TwoReads(),
            tools,
            username="maya",
            company_slug="summit",
            companies=("summit", "pebble"),
        )
        assert result.original_request == original and result.outcome == "completed"
        assert len(tools.started) == 2
        assert all(s.status == "completed" for s in result.subtasks)
        for step in result.subtasks:
            assert [
                entry.status for entry in result.trace if entry.subtask_id == step.id
            ] == ["running", "completed"]

    run(check())


def test_invalid_model_plan_is_safe_failure_without_dispatch():
    class InvalidLLM(FakeLLM):
        async def plan(self, original_request):
            return {
                "steps": [
                    {
                        "id": "write",
                        "tool": "execute_sql",
                        "args": {"sql": "DELETE FROM users"},
                    }
                ]
            }

    async def check():
        tools = GatedReads()
        result = await execute(
            uuid4(),
            "original",
            ActorContext(uuid4(), uuid4(), "employee"),
            InvalidLLM(),
            tools,
            username="maya",
            company_slug="summit",
            companies=("summit", "pebble"),
        )
        assert result.status == "failed" and result.error == "planning_failed"
        assert not tools.started and result.original_request == "original"

    run(check())
