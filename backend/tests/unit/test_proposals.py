"""Strict optimistic concurrency tokens and reviewable proposal payloads."""

import pytest
from pydantic import ValidationError

from app.schemas.proposals import ProposalVersion


@pytest.mark.parametrize("value", [0, -1, True, "1", 1.5, 2147483648])
def test_expected_version_is_a_positive_strict_database_integer(value):
    with pytest.raises(ValidationError):
        ProposalVersion(expected_version=value)
