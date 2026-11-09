"""Record exact model/chunker/source identity of each atomic policy index."""

import sqlalchemy as sa
from alembic import op

revision = "0003_rag_provenance"
down_revision = "0002_guards"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("indexed_model", "indexed_revision", "indexed_chunker"):
        op.add_column("policies", sa.Column(name, sa.Text(), nullable=True))
    for name in ("indexed_source_sha256", "index_fingerprint"):
        op.add_column("policies", sa.Column(name, sa.String(64), nullable=True))
    op.add_column(
        "policies", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    for name in (
        "indexed_at",
        "index_fingerprint",
        "indexed_source_sha256",
        "indexed_chunker",
        "indexed_revision",
        "indexed_model",
    ):
        op.drop_column("policies", name)
