# DOCUMENT 7 — README Template and Submission Checklist

> Template for the *implemented* repository. Replace placeholders only with observed facts; do not report blueprint commands as executed tests.

# HR Chat Assistant

A multi-tenant HR assistant for fictional Summit Dental and Pebble Retail. Supports authorized policy RAG, structured leave queries, streaming multi-step execution, mid-run instruction updates and explicitly confirmed leave booking. Built as an AI Engineer take-home demonstration.

## Quickstart

```bash
cp .env.example .env
# Set DEMO_SEED_PASSWORD and optional live LLM credentials in .env
# Confirm local embedding weights are installed/cached, or allow initial model download
docker compose up --build -d
# If migrations/seeding are not handled by the start command:
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed.load_seed
# Open frontend URL documented by compose configuration
```

**Actual port values:** `[fill from compose]`. **Prerequisites:** Docker Engine + Compose, memory for local embedding model, optional Python/npm for local development. Do not publish `.env`, secrets or personal HR data. Document differences in Windows PowerShell commands if applicable.

## Demo identities

| User | Company | Role | Seeded balance |
|---|---|---|---|
| maya | Summit Dental | employee | 12 |
| leila | Summit Dental | HR | not specified by assignment |
| ravi | Pebble Retail | employee | 5 |

Demo password is generated from an environment variable during seed; no real company accounts are accessed.

## Architecture in one paragraph

React chat sends authenticated requests to FastAPI. A persisted task runner plans substeps, calls scoped SQL/pgvector tools, emits SSE events and checkpoints mid-run notes. PostgreSQL stores task/events, leave records, document metadata and 384-dimensional embeddings. Retrieved policy text is untrusted; tenant/role filtering is applied in SQL before LLM context. All leave writes are bound to an explicitly accepted, versioned proposal and run under transaction locks.

## How tasks are routed

- **Search policy:** RAG with tenant, role, document status/version and citation filters.
- **Structured facts:** SQL for balance/history, no vector store for mutable numbers.
- **Conversational:** direct non-sensitive response when no tenant data needed.
- **Multi-task:** planner executes independent reads concurrently and combines tool results.
- **Refusal:** unauthorized tenant/role/user data never enters model context.
- **Mid-run note:** append message and increment current task revision; runner consumes at checkpoint, retaining original request; active generation may cancel/restart.
- **Writes:** create proposal first; no booking/balance update until authenticated confirmation; lock/revalidate in transaction.

## Demo scenarios and evidence

1. Maya: “What happens if I arrive late three times?” → Summit one-day pay cut.
2. Ravi asks same → Pebble warning only.
3. Maya: “How many leave days?” → 12. Ravi → 5.
4. Maya tries CEO pay and Pebble handbook → denied. Leila can access Summit CEO document only; CEO *monetary band* not supplied by assignment.
5. Maya sends balance + lateness + 3-day leave request → multiple subtasks; missing dates clarified.
6. While running, Maya sends an extra instruction → same task ID, updated plan and stream.
7. Maya proposes dates → no leave mutation; click confirm → exactly one booking, correct balance; duplicate confirm prevented.
8. Poisoned Summit document appears in policy corpus → assistant does not obey its unauthorized disclosure instruction.

## Security and data provenance

Exact assignment facts distinguished from fictional demonstration files (`seed/policies/**` metadata). Authenticating user controls tenant and role, not frontend-provided IDs. Parameterized SQL, source ACL filters, tool allowlist, HttpOnly cookie/CSRF, proposal ownership, restricted logs and audit records. RLS optional defense in depth and not a substitute for app checks.

## Testing

```bash
# Fill exact implemented paths/commands
python -m pytest -q backend/tests/unit
python -m pytest -q backend/tests/integration
python -m pytest -q backend/tests/security
```

Tests use deterministic fake LLM and real local embeddings and PostgreSQL/pgvector. No external LLM key required for tests. Report tests run, passed, failed, skipped and environment, based on actual CLI output: `[fill]`.

## Tradeoffs and recommendations

**Keep:** modular monolith, strict actor-based authorization, local keyless vector tests, event persistence, approval transactions. **Change with scale:** robust durable worker queue, tracing/redaction/alerts, SSO, reviewed ingestion, encrypted secrets, CI/CD, lifecycle policies. **If separate DBs already exist:** tenant registry plus server-side routing to isolated credentials/connection pools; run migrations independently per tenant; avoid cross-tenant joins and centrally store only non-sensitive task metadata. This is more operationally expensive than shared DB with tenant-scoped RLS, but may fit compliance constraints.

## Skipped and limitations (fill truthfully)

`[Specify missing production features, tests, known limitations, fallback LLM behavior and recovery constraints. Do not claim full production readiness.]`

**Actual engineering hours spent:** `[fill from real time log, never invent]`.

## Final submission checklist

- [ ] `README.md` with quickstart, architecture, recommendations, omissions, actual hours
- [ ] `docker-compose.yml` with healthchecks and database/pgvector
- [ ] `.env.example` with no real secrets
- [ ] Backend + migrations + real policy ingestion, vector search, SQL tools
- [ ] Seed data exact assignment identities/balances/policy restrictions
- [ ] Poisoned policy seeded and blocked from affecting tool behavior
- [ ] Keyless real-embedding and real-pgvector integration tests
- [ ] Tenant/role/self tests; Leila cannot access Pebble
- [ ] One-message multi-intent orchestration
- [ ] True mid-run notes on SAME task and persistent state
- [ ] SSE events, replay and live UI while job running
- [ ] Proposal screen and commit-only-on-confirm test
- [ ] Duplicate/stale/concurrent confirmation protection
- [ ] Clean Docker build + test commands observed working
- [ ] Known omissions and actual work hours transparently reported
- [ ] No secrets, private real HR data or generated model cache committed

## Recommended demo order

Start Compose → login as Maya → balance/late query → multi-intent request → add in-flight note → proposal without mutation → confirm once → try duplicate confirm → login Ravi for other policy → login Leila for confidential Summit policy → run security tests (poison, tenant isolation) → show README tradeoffs. Keep demonstration focused on reliability rather than UI animation.
