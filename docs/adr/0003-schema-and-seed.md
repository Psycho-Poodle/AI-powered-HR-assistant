# ADR 0003: Tenant-integrity schema and immutable seed baseline

Date: 2026-11-07
Status: Implemented for Phase 2 only.

## Schema

SQLAlchemy models implement all 15 tables in document 03. Alembic revision
`0001_schema` is a frozen schema snapshot, independent of future ORM changes.
It installs `vector` and `pgcrypto`, UUID defaults, timezone-aware timestamps,
checks, unique constraints and indexes. Every foreign key to a tenant-owned
record includes `company_id`; nullable specific-user policy recipients must
also belong to the policy tenant. Generic audit object IDs are intentionally
polymorphic, not relational foreign keys. `policy_chunks.embedding` is
`vector(384)`, with no vectors or retrieval code populated in this phase.
The unique proposal-booking and task-event sequence constraints exist, but
booking and event-allocation services do not.

Revision `0002_guards` forces tenant RLS on all 14 tenant tables and fails
closed without a transaction-local `app.tenant_id`. It protects append-only
task notes/events, leave history and audit logs against updates, deletes and
truncation; creation/ingestion timestamps and original task requests are
immutable. The policies are tenant-only defense in depth; self-record/visibility
enforcement and authenticated actor context remain Phase 3 work. Superuser and
BYPASSRLS bootstrap connections bypass RLS, so tests exercise a separate
nonprivileged role as well. No runtime role or authentication is added here.

Downgrade removes schema objects in dependency order while retaining the
infrastructure extensions, including the Phase 1 vector extension. The database
contains no prior application rows, so there is no data backfill to perform.

## Seed

JSON identity/balance manifests plus a policy manifest and Markdown sources
provide 2 companies, 3 users, 2 balances and 6 policies. Four policy sources are
assignment-derived; two annual-leave examples are visibly labeled FICTIONAL
DEMONSTRATION DATA in both title and body and stored with `is_demo=true` and
`provenance=fictional_demo`. These examples specify no real employer entitlement.
The CEO salary source is specific-user Leila-only and explicitly lacks a
numeric band. The poison remains ordinary untrusted Summit document text;
no prompt-injection defense or policy retrieval implementation is claimed yet.
No profiles, leave requests, task events or model-generated embeddings are seeded.
Published status describes source document availability, not completed indexing;
Phase 4 must create embeddings before retrieval can exist.

The loader validates manifests, scopes source paths to `seed/policies`, hashes
raw source bytes with SHA-256, records source/ACL/version/provenance/timestamps,
and uses deterministic UUIDs. The caller owns one transaction; a seed advisory
lock and uniqueness constraints serialize repeats. A policy body/hash or metadata
conflict raises instead of overwriting an existing version. Use a new version
for legitimate policy changes. Repeated runs do not reset balances or rotate
passwords. Passwords are salted Argon2id hashes created from the required
`DEMO_SEED_PASSWORD`; no default password is shipped. Seeding is not an auth flow.

## Verification isolation

`scripts/verify_phase2.py` compares dev/test cluster identifiers via local Docker
psql, creates temporary credentials and a disposable test database, and runs
the real suite. The dev-side temporary role is read-only and monitors cluster
identity; schema/seed writes occur exclusively in the disposable test database.
The suite guards the database name/cluster, checks model/migration agreement,
rolls back each test, and exercises downgrade/re-upgrade. Cleanup removes only
the uniquely named disposable database and roles created by that invocation.
It does not rotate stored credentials or reset the existing dev/test databases.

The user's `.env` passwords currently differ from persistent volume credentials.
Tests therefore use temporary roles via local Docker bootstrap access instead
of changing existing credentials. Host migration/seed commands require a valid
connection URL; correcting existing credentials is left to the operator.

Phase 3 remains unauthorized after this phase: no auth, API tenant isolation,
RAG, leave tools, orchestration, UI or streaming was implemented.
