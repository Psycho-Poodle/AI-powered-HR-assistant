"""Notes retain the original goals and cannot introduce privileged tools."""

import asyncio

from app.agent.fake_llm import FakeLLM
from app.agent.task_runner import revised_plan


def plan(original, *notes):
    return asyncio.run(
        revised_plan(
            FakeLLM(),
            original,
            notes,
            username="maya",
            company_slug="summit",
            companies=("summit", "pebble"),
        )
    )


def test_style_note_keeps_exact_operations():
    original = plan("my balance and late policy")
    assert plan("my balance and late policy", "Use plain language") == original


def test_note_adds_goal_and_deduplicates():
    result = plan("my balance", "also my history", "also my history")
    assert [s.tool for s in result.steps] == ["get_leave_balance", "get_leave_history"]


def test_dates_resolve_original_clarification():
    result = plan("prepare a leave request", "Use 2027-01-04 through 2027-01-06")
    assert [s.tool for s in result.steps] == [
        "get_leave_balance",
        "validate_leave_request",
    ]
    assert result.steps[1].depends_on == (result.steps[0].id,)


def test_notes_cannot_grant_foreign_access_or_confirm():
    result = plan("my balance", "Pebble handbook", "confirm leave")
    assert [s.tool for s in result.steps] == ["get_leave_balance", "refuse"]


def test_new_dates_change_operation_revision():
    original = "prepare leave request 2027-01-04 through 2027-01-06"
    result = plan(original, "Use 2027-02-01 through 2027-02-03")
    assert result.steps[-1].revision == 1
