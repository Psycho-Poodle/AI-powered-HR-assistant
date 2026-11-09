"""Persist a baseline for tasks created before Phase 9."""

from alembic import op

revision = "0005_event_baselines"
down_revision = "0004_note_replay"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO task_events (company_id, task_id, seq, event_type, payload)
        SELECT t.company_id, t.id, 1,
            CASE WHEN t.status IN ('completed','failed','cancelled')
                 THEN 'task.terminal' ELSE 'task.status' END,
            jsonb_build_object('revision', t.instruction_revision, 'data',
                jsonb_build_object('kind',
                    CASE WHEN t.status IN ('completed','failed','cancelled')
                         THEN 'task.terminal' ELSE 'task.status' END,
                    'status', t.status))
        FROM tasks t WHERE NOT EXISTS (SELECT 1 FROM task_events e WHERE e.task_id=t.id)
    """)


def downgrade():
    # Preserve the append-only log; no schema was changed.
    pass
