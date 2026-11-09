# ADR 0001: HR assistant architecture baseline

Date: 2026-11-04
Status: Accepted design; only the Phase 0 API foundation is implemented.

## Context

Reviewed docs 01-08 and both pages of `assignment/Task-AI-Engineer 1.pdf`.
The repository initially contained only those source documents and had a clean
Git status. The PDF mandates Python, PostgreSQL/pgvector, real embeddings in
keyless tests, isolated companies, streaming, updates to the same running job,
and human confirmation before leave changes. Frameworks, model choice and the
details below are design choices rather than additional assignment mandates.

## Decisions

- Use a modular monolith with FastAPI and Python 3.12+. Start with only public
  `GET /api/v1/health/live` returning `{"status":"ok"}`. Keep readiness separate
  until dependencies exist. No runtime configuration is needed for this slice.
- Use a custom typed planner/executor with allowlisted tools and explicit
  checkpoints. This keeps task dependencies and authorization reviewable without
  a graph framework or autonomous agent swarm. Independent reads may later run
  concurrently; never expose a generic LLM SQL executor.
- Derive an immutable `ActorContext(user_id, company_id, role)` on the server
  from authenticated identity. Recheck tenant, visibility and ownership for
  every read/write before data reaches model context. Client fields, model
  arguments and retrieved text cannot grant permissions. Leila's CEO-document
  permission is user-specific; HR role alone is insufficient.
- Use shared PostgreSQL with tenant-scoped tables, composite tenant foreign keys,
  application checks and RLS as defense in depth. Use pgvector for policy
  retrieval and ordinary SQL for mutable balances. If existing separate company
  databases must be retained, use server-controlled tenant routing and separate
  pools/migrations; this adds operational cost.
- Use local `sentence-transformers/all-MiniLM-L6-v2` embeddings with 384
  dimensions and cosine distance. Later pin/cache model assets for offline,
  keyless tests using real embeddings and real pgvector. Stub only the LLM.
  Filter tenant/status/access before model context; treat retrieved text,
  including the poisoned policy, as untrusted reference data.
- Persist immutable original requests, append-only task notes/revisions and
  ordered events. A note updates the same task at safe checkpoints. Persist
  events before SSE delivery for replay; use leases/checkpoints for single-node
  recovery. Mid-generation changes may require cancellation and restart.
- Create a versioned proposal before any leave booking or balance change.
  Only explicit authenticated owner confirmation may commit the transaction,
  after locks and renewed permission, expiry, balance and overlap checks.
  Uniqueness prevents duplicate bookings. Proposal metadata is distinct from
  booked leave; model output can never count as user confirmation.

## Consequences and scope

This favors explicit, testable boundaries over distributed infrastructure.
Shared storage requires careful authorization and RLS testing. A single-process
runner has recovery and scaling limits to address in its designated phase.
Local models require cached assets; a fake LLM does not replace vector tests.
The PDF provides no numeric CEO salary band; future fixtures must not invent an
assignment fact. Fictional demo policies must be labeled as such.

Phase 0 adds only `backend/pyproject.toml`, `backend/app/__init__.py`,
`backend/app/main.py`, `backend/tests/unit/test_health.py`, `.gitignore`,
`README.md`, and this ADR. Existing source documents remain unchanged.
No frontend scaffold, database, RAG, actor/auth implementation, orchestrator,
proposal service, task runner or streaming is included. No settings validation
test is needed until settings exist. Phase 1 requires separate authorization
and adds Docker/PostgreSQL/pgvector without application tables.
