"""Planning sees the request; composition receives already-authorized results."""

from typing import Protocol

from app.agent.state import Plan, SubtaskResult


class LLM(Protocol):
    async def plan(self, original_request: str) -> Plan: ...

    async def compose(
        self, original_request: str, subtasks: tuple[SubtaskResult, ...]
    ) -> str: ...
