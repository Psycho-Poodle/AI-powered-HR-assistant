"""The demo calendar is explicit, bounded, inclusive and not employer policy."""

import base64
import json
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.hr import LeaveValidationInput
from app.services.leave import HRToolError, decode_cursor, weekday_days


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("2026-11-09", "2026-11-09", 1),
        ("2026-11-14", "2026-11-15", 0),
        ("2026-11-13", "2026-11-16", 2),
        ("2026-11-09", "2026-11-15", 5),
        ("2026-11-09", "2026-11-22", 10),
        ("2028-02-28", "2028-03-01", 3),
        ("9999-12-31", "9999-12-31", 1),
    ],
)
def test_inclusive_weekday_demo_calendar(start, end, expected):
    assert weekday_days(date.fromisoformat(start), date.fromisoformat(end)) == expected


@pytest.mark.parametrize(
    "start,end,code",
    [
        (date(2026, 11, 10), date(2026, 11, 9), "date_order"),
        (date(2026, 1, 1), date(2027, 1, 2), "range_too_long"),
    ],
)
def test_invalid_calendar_range(start, end, code):
    with pytest.raises(HRToolError) as error:
        weekday_days(start, end)
    assert error.value.code == code


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",
        "20261109",
        "2026-11-09T00:00:00",
        1794182400,
        datetime(2026, 11, 9),
    ],
)
def test_validation_dates_are_real_iso_calendar_dates(value):
    with pytest.raises(ValidationError):
        LeaveValidationInput(start_date=value, end_date="2026-11-10")


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": "maya"},
        {"company_id": "pebble"},
        {"role": "hr"},
        {"leave_type": "sick"},
    ],
)
def test_validation_rejects_authority_and_unsupported_type(changes):
    with pytest.raises(ValidationError):
        LeaveValidationInput(
            **(dict(start_date="2026-11-09", end_date="2026-11-10") | changes)
        )


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        [None, {}],
        ["not-a-date", "not-a-uuid"],
        ["2026-11-09T00:00:00", "bad"],
        [1, 2],
    ],
)
def test_invalid_cursor_structure_is_predictable(value):
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(HRToolError) as error:
        decode_cursor(cursor)
    assert error.value.code == "invalid_cursor"
