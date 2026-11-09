"""Tenant RLS and immutable/append-only history guards."""

from alembic import op

revision = "0002_guards"
down_revision = "0001_schema"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "users",
    "employee_profiles",
    "policies",
    "policy_chunks",
    "leave_balances",
    "conversations",
    "messages",
    "tasks",
    "task_messages",
    "task_events",
    "action_proposals",
    "leave_requests",
    "leave_history",
    "audit_logs",
)
APPEND_ONLY = ("task_messages", "task_events", "leave_history", "audit_logs")
CREATED_TABLES = (
    "companies",
    "users",
    "policy_chunks",
    "conversations",
    "messages",
    "tasks",
    "task_messages",
    "task_events",
    "action_proposals",
    "leave_requests",
    "audit_logs",
)


def upgrade():
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        predicate = (
            "company_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        )
        op.execute(
            f'CREATE POLICY tenant_scope ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    op.execute("""
        CREATE FUNCTION reject_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'append-only record cannot be changed'
                USING ERRCODE='23514';
        END $$
    """)
    for table in APPEND_ONLY:
        op.execute(
            f'CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION reject_history_mutation()"
        )
        op.execute(
            f'CREATE TRIGGER no_truncate BEFORE TRUNCATE ON "{table}" '
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_history_mutation()"
        )
    op.execute("""
        CREATE FUNCTION preserve_created_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'created_at is immutable' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in CREATED_TABLES:
        op.execute(
            f'CREATE TRIGGER immutable_created_at BEFORE UPDATE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION preserve_created_at()"
        )
    op.execute("""
        CREATE FUNCTION preserve_ingested_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.ingested_at IS DISTINCT FROM OLD.ingested_at THEN
                RAISE EXCEPTION 'ingested_at is immutable' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER immutable_ingested_at BEFORE UPDATE ON policies "
        "FOR EACH ROW EXECUTE FUNCTION preserve_ingested_at()"
    )
    op.execute("""
        CREATE FUNCTION preserve_original_request() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.original_request IS DISTINCT FROM OLD.original_request THEN
                RAISE EXCEPTION 'original_request is immutable' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER immutable_original_request BEFORE UPDATE ON tasks "
        "FOR EACH ROW EXECUTE FUNCTION preserve_original_request()"
    )


def downgrade():
    op.execute("DROP TRIGGER immutable_ingested_at ON policies")
    op.execute("DROP FUNCTION preserve_ingested_at()")
    op.execute("DROP TRIGGER immutable_original_request ON tasks")
    op.execute("DROP FUNCTION preserve_original_request()")
    for table in CREATED_TABLES:
        op.execute(f'DROP TRIGGER immutable_created_at ON "{table}"')
    op.execute("DROP FUNCTION preserve_created_at()")
    for table in APPEND_ONLY:
        op.execute(f'DROP TRIGGER append_only ON "{table}"')
        op.execute(f'DROP TRIGGER no_truncate ON "{table}"')
    op.execute("DROP FUNCTION reject_history_mutation()")
    for table in TENANT_TABLES:
        op.execute(f'DROP POLICY tenant_scope ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
