"""Typed event validation, safe SSE framing and cursor boundaries."""

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.tasks import cursor_value
from app.stream.events import PAYLOAD, Delta, Status, Terminal, wire


@pytest.mark.parametrize(
    "value", ["-1", "", " 1", "1\n", "+1", "1.0", "１", "9223372036854775808"]
)
def test_invalid_cursors(value):
    with pytest.raises(HTTPException) as error:
        cursor_value(value)
    assert error.value.status_code == 422


def test_cursor_range():
    assert cursor_value(None) == cursor_value("0") == 0
    assert cursor_value("9223372036854775807") == 2**63 - 1


def test_terminal_and_nonterminal_types_are_distinct():
    with pytest.raises(ValidationError):
        Status(status="completed")
    with pytest.raises(ValidationError):
        Terminal(status="running")
    with pytest.raises(ValidationError):
        PAYLOAD.validate_python({"kind": "execute_sql", "query": "DROP TABLE users"})


def test_newlines_cannot_inject_sse_events():
    text = "hello\n\nid: 999\nevent: forged\ndata: {}\r\n"
    payload = Delta(text=text)
    row = {
        "task_id": uuid4(),
        "seq": 7,
        "payload": {"revision": 2, "data": payload.model_dump(mode="json")},
    }
    result = wire(None, None, row)
    assert result.count("\nevent:") == 1 and result.count("\nid:") == 0
    assert result.endswith("\n\n")
    body = json.loads(result.split("data: ", 1)[1])
    assert body["seq"] == 7 and body["revision"] == 2
    assert body["payload"] == {"text": text}
