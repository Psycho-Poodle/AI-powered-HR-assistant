"""Static checks for references and invalid seed metadata."""

import pytest
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint

from app.db.base import Base
from app.db.models import PolicyChunk
from app.seed.load_seed import PolicyRecord


def test_all_tenant_references_are_composite():
    assert len(Base.metadata.tables) == 15
    assert PolicyChunk.__table__.c.embedding.type.dim == 384
    for table in Base.metadata.tables.values():
        if table.name == "companies":
            continue
        assert not table.c.company_id.nullable
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            if constraint.referred_table.name != "companies":
                assert list(constraint.column_keys)[0] == "company_id"
                assert len(constraint.column_keys) == 2


@pytest.mark.parametrize(
    "visibility,allowed", [("all", "leila"), ("specific_user", None)]
)
def test_seed_manifest_rejects_inconsistent_visibility(visibility, allowed):
    with pytest.raises(ValidationError):
        PolicyRecord(
            company="summit",
            slug="x",
            title="x",
            version=1,
            visibility=visibility,
            allowed_user=allowed,
            status="published",
            provenance="assignment",
            file="summit/x.md",
        )


def test_seed_manifest_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PolicyRecord(
            company="summit",
            slug="x",
            title="x",
            version=1,
            visibility="all",
            status="published",
            provenance="assignment",
            file="summit/x.md",
            role="hr",
        )
