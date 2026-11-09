"""Idempotent append-only client note submissions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_note_replay"
down_revision = "0003_rag_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "task_messages", sa.Column("client_note_id", sa.Uuid(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_task_messages_task_id_client_note_id",
        "task_messages",
        ["task_id", "client_note_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_task_messages_task_id_client_note_id", "task_messages", type_="unique"
    )
    op.drop_column("task_messages", "client_note_id")
