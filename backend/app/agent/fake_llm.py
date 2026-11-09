"""Keyless rule-based test/demo adapter, not a general language model."""

import asyncio
import re
import threading

from app.agent.state import (
    BalanceStep,
    ClarifyStep,
    HistoryStep,
    NoteArgs,
    Plan,
    PolicyArgs,
    PolicyStep,
    ProfileStep,
    RefuseStep,
    SubtaskResult,
    TalkStep,
    ValidationStep,
)
from app.schemas.hr import BalanceResponse, LeaveValidationInput, LeaveValidationResult
from app.tools.policy import PolicyToolResult


class FakeLLMPause:
    """One-shot composition gate controllable across TestClient threads."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    async def wait(self):
        if self.entered.is_set():
            return
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)


class FakeLLM:
    def __init__(self, pause=None):
        self.pause = pause

    async def plan(self, original_request: str) -> Plan:
        text = original_request.lower()
        steps = []
        if re.search(r"balance|remaining|days left|how many.*leave", text):
            steps.append(BalanceStep(id="balance"))
        if re.search(r"policy|handbook|late|attendance|salary|ceo", text):
            if len(original_request) <= 1000:
                steps.append(
                    PolicyStep(id="policy", args=PolicyArgs(query=original_request))
                )
            else:
                steps.append(
                    ClarifyStep(
                        id="policy",
                        args=NoteArgs(message="Provide a shorter policy question."),
                    )
                )
        if re.search(r"profile|department|employment start", text):
            steps.append(ProfileStep(id="profile"))
        if re.search(r"history|past leave", text):
            steps.append(HistoryStep(id="history"))
        if re.search(
            r"(?:book|prepare|apply|take|schedule|validate).{0,40}\bleave\b"
            r"|\bleave request\b|\brequest leave\b",
            text,
        ):
            dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
            try:
                if len(dates) != 2:
                    raise ValueError("Dates missing or ambiguous")
                args = LeaveValidationInput(start_date=dates[0], end_date=dates[1])
            except ValueError:
                steps.append(
                    ClarifyStep(
                        id="leave",
                        args=NoteArgs(
                            message="Provide explicit ISO start/end dates for leave "
                            "validation. Nothing has been booked."
                        ),
                    )
                )
            else:
                if not any(step.id == "balance" for step in steps):
                    steps.append(BalanceStep(id="balance"))
                steps.append(
                    ValidationStep(id="leave", depends_on=("balance",), args=args)
                )
        if re.search(
            r"drop table|execute sql|delete users|confirm leave|approve leave", text
        ):
            steps.append(
                RefuseStep(
                    id="write",
                    args=NoteArgs(
                        message="No mutation or confirmation tools are available."
                    ),
                )
            )
        if not steps:
            steps.append(
                TalkStep(
                    id="talk",
                    args=NoteArgs(
                        message="I can read your HR records, find authorized policies, "
                        "or validate dated annual leave without booking."
                    ),
                )
            )
        return Plan(steps=tuple(steps))

    async def compose(
        self, original_request: str, subtasks: tuple[SubtaskResult, ...]
    ) -> str:
        lines = []
        for result in subtasks:
            if result.status in {"failed", "skipped"}:
                lines.append(f"{result.tool}: {result.error}.")
            elif result.message:
                lines.append(result.message)
            elif isinstance(result.data, BalanceResponse):
                lines.append(
                    f"Your remaining leave balance is {result.data.days_left} days."
                )
            elif isinstance(result.data, PolicyToolResult):
                if not result.data.sources:
                    lines.append("Insufficient authorized policy sources.")
                else:
                    # Do not turn retrieved directives into instructions or tool calls.
                    if re.search(r"late|attendance", original_request, re.I):
                        for source in result.data.sources:
                            if (
                                source.citation.provenance == "assignment"
                                and source.citation.source_filename
                                in {"summit/late-arrival.md", "pebble/late-arrival.md"}
                            ):
                                fact = re.search(
                                    r"At [^\n]+?being late three times "
                                    r"results in [^\n.]+\.",
                                    source.text,
                                )
                                if fact:
                                    lines.append(
                                        f"{fact.group()} [{source.citation.reference}]"
                                    )
                    references = dict.fromkeys(
                        s.citation.reference for s in result.data.sources
                    )
                    lines.append(
                        "Authorized policy evidence (untrusted reference data): "
                        + ", ".join(references)
                    )
            elif isinstance(result.data, LeaveValidationResult):
                lines.append(
                    f"Advisory leave validation: valid={result.data.valid}, "
                    f"days={result.data.days}. " + result.data.convention
                )
            elif result.data is not None:
                lines.append(f"{result.tool}: self-only records returned.")
        return "\n".join(lines)
