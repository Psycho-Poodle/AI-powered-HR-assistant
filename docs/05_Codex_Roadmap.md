# DOCUMENT 5 — Codex Implementation Roadmap and Phase-Specific Prompts

## 1. Working agreement with Codex

Build one phase at a time. Before any edit, inspect repo tree, git status and existing files; read `01_PRD.md` through `07_README_and_Checklist.md`, especially PDF-derived facts and security assumptions. Do not overwrite unrelated work. For each phase: (1) report intended files; (2) implement smallest testable slice; (3) execute named tests; (4) summarize changed files, commands, test results, unsolved issues; (5) update architecture notes; (6) STOP for next phase. Never claim test success without tool output. Maintain `.env.example` but never commit `.env` or credentials. Use the exact assignment baseline. Any added behavior is explicitly “fictional demo” or “production enhancement”.

**Canonical directory tree (target, not existing files):**

```text
hr-chat-assistant/
  README.md
  .env.example
  .gitignore
  docker-compose.yml
  Makefile
  docs/
    01_PRD.md
    02_Technical_Design.md
    03_Database_and_API.md
    04_Mock_Data_and_Ingestion.md
    05_Codex_Roadmap.md
    06_Testing_and_Acceptance.md
    07_README_and_Checklist.md
    08_Master_Codex_Prompt.md
  backend/
    Dockerfile
    pyproject.toml
    alembic.ini
    migrations/env.py
    migrations/versions/
    app/
      main.py
      core/config.py
      core/logging.py
      auth/dependencies.py
      auth/security.py
      api/auth.py
      api/me.py
      api/conversations.py
      api/tasks.py
      api/policies.py
      api/leave.py
      db/base.py
      db/session.py
      db/models.py
      schemas/auth.py
      schemas/chat.py
      schemas/hr.py
      repositories/policies.py
      repositories/tasks.py
      repositories/leave.py
      services/leave.py
      services/ingestion.py
      agent/llm_protocol.py
      agent/fake_llm.py
      agent/planner.py
      agent/executor.py
      agent/tool_registry.py
      agent/state.py
      tools/policy.py
      tools/leave.py
      rag/embeddings.py
      rag/ingest.py
      rag/search.py
      security/authorization.py
      security/prompt_injection.py
      tasks/runner.py
      tasks/recovery.py
      stream/events.py
      seed/load_seed.py
    tests/
      conftest.py
      unit/
      integration/
      security/
  frontend/
    Dockerfile
    package.json
    vite.config.ts
    tsconfig.json
    src/
      main.tsx
      app/App.tsx
      api/client.ts
      api/events.ts
      components/LoginForm.tsx
      components/Sidebar.tsx
      components/ChatPanel.tsx
      components/MessageComposer.tsx
      components/TaskActivity.tsx
      components/ProposalCard.tsx
      hooks/useTaskStream.ts
      pages/LoginPage.tsx
      pages/WorkspacePage.tsx
      styles/global.css
  seed/
    companies.json
    users.json
    leave_balances.json
    policies/summit/*.md
    policies/pebble/*.md
  scripts/
    bootstrap.sh
    verify_demo.sh
```

Responsibilities: `api/` HTTP endpoints; `db/` mappings and sessions; `schemas/` validation; `repositories/` authorized database access; `services/` business transactions; `agent/` task planning/execution; `tools/` typed tool adapters; `rag/` ingest/vector search; `security/` immutable actor and permissions; `tasks/` leases/recovery; `stream/` SSE sequencing; `seed/` repeatable fixtures; UI components separate state/display. Combine trivial modules if a smaller architecture remains clear.

## 2. Dependency order

Phase 0 baseline → 1 infrastructure → 2 schema/seed → 3 auth/isolation → 4 RAG → 5 SQL tools → 6 planner → 7 proposals → 8 durable tasks/notes → 9 streaming → 10 React → 11 security/integration → 12 docs/demo. Implement minimal task persistency already in phase 6, then strengthen it in phase 8. No phase should depend on a future UI to test backend behavior.

---

## Phase 0 — Repo foundation and architecture freeze

**Objective:** inspect repository, import docs, establish Python/TS tooling and decisions. **Files:** `README.md`, `docs/*.md`, `.gitignore`, `backend/pyproject.toml`, `backend/app/main.py`, `backend/tests/unit/test_health.py`, `frontend/package.json` (scaffold only). **Dependencies:** none. **Tasks:** inspect existing work; create ADR on task runner/embedding model/tenant model; configure Ruff, pytest, Python path, typed settings; GET health. **Unit:** settings validation, health route. **Integration:** FastAPI test client response. **Commands:** `git status --short`, `python -m pytest backend/tests/unit -q`, `ruff check backend` (with environment installed). **Acceptance/DoD:** health test passes, docs read, no unnecessary runtime infra, actual diff reported.

**Codex prompt:**
> Read docs 01–08 and the original PDF. Inspect the current repository before touching files. Implement **Phase 0 only**: minimal FastAPI entry, Python project config, backend health unit test, gitignore and architecture decision notes. Do not build RAG, database, UI or other phases. Run available tests/lint, report exact results and stop.

## Phase 1 — Docker/PostgreSQL/pgvector

**Objective:** reproducible Postgres and API container. **Files:** `docker-compose.yml`, `backend/Dockerfile`, `.env.example`, `backend/app/db/session.py`, `backend/tests/integration/test_db_connection.py`. **Dependencies:** phase 0. **Tasks:** pin pgvector-enabled Postgres image; healthcheck `pg_isready`; create dedicated test DB/service; install `vector`; DSN from environment; run startup health query; separate credentials for dev/tests. **Unit:** config URL validation. **Integration:** `SELECT extversion FROM pg_extension WHERE extname='vector'`. **Commands:** `docker compose up -d db db_test`, `docker compose exec db psql -U ... -c 'SELECT 1;'`, `python -m pytest ...test_db_connection.py -q`. **DoD:** real vector extension query passes, persistent volume, no secrets in Git.

**Codex prompt:**
> Implement Phase 1 only. Add a Docker Compose PostgreSQL/pgvector service and test DB, API Dockerfile, environment settings and real integration test verifying the vector extension. Keep host ports configurable. Do not implement tables yet. Prove test DB is isolated from dev DB, run tests, report outputs, stop.

## Phase 2 — Schema and immutable seed baseline

**Objective:** migrations + exact tenant facts. **Files:** `backend/app/db/models.py`, `backend/migrations/{env.py,versions/*}`, `backend/app/seed/load_seed.py`, `seed/companies.json`, `seed/users.json`, `seed/leave_balances.json`, `seed/policies/*`, `backend/tests/integration/test_seed.py`. **Dependencies:** phase 1. **Tasks:** implement full tenant-scoped schema, composite FKs, constraints and pgvector column, append-only task events, proposal uniqueness; create idempotent seed with only assignment data and clearly marked fictional docs; hash passwords from env; avoid seeding fake CEO *numeric* band as assignment truth. **Unit:** schema validation, seed manifest parser. **Integration:** migrations from empty DB, second seed is no-op, exact balances and policies. **Commands:** `alembic upgrade head`, `python -m app.seed.load_seed`, `python -m pytest tests/integration/test_seed.py -q`. **DoD:** no cross-tenant FK possible, complete repeatable schema and seed.

**Codex prompt:**
> Implement Phase 2 only using the schema and mock-data docs. Write models, Alembic migrations and idempotent seed. Preserve exact assignment facts, visibly label additional policies fictional. Add real DB tests for seed repeatability and tenant FK constraints. Do not build authentication/RAG. Report commands and stop.

## Phase 3 — Authentication, self access and isolation

**Objective:** trust boundary independent of LLM. **Files:** `backend/app/auth/{security.py,dependencies.py}`, `backend/app/security/authorization.py`, `backend/app/api/{auth.py,me.py}`, `backend/app/repositories/{policies.py,leave.py}`, `backend/tests/security/test_isolation.py`. **Dependencies:** phase 2. **Tasks:** hashed credential verification, secure session cookie, CSRF protection on cookie mutations, immutable actor derived server-side, tenant+role scoping on every read; optionally RLS with `SET LOCAL` transaction var; non-enumerating responses. **Unit:** actor permissions matrix. **Integration:** identity login, Maya/Ravi isolation, Leila only Summit HR. **Commands:** `pytest tests/security/test_isolation.py -q`; smoke `POST /auth/login`, `GET /me`. **DoD:** impossible to select other tenant via client fields, protected rows never returned.

**Codex prompt:**
> Implement Phase 3 only. Add demo authentication and server-derived immutable ActorContext. Enforce tenant, visibility and self-record rules in repository queries and API dependencies. Add adversarial tests for forged company/role/IDs and Leila's lack of Pebble access. Do not rely on model prompts for security. Run tests and stop.

## Phase 4 — Real embeddings and policy RAG

**Objective:** source-grounded, filtered retrieval. **Files:** `backend/app/rag/{embeddings.py,ingest.py,search.py}`, `backend/app/services/ingestion.py`, `backend/app/tools/policy.py`, `backend/app/api/policies.py`, `backend/tests/integration/test_rag.py`, `backend/tests/security/test_poison.py`. **Dependencies:** phases 2–3. **Tasks:** local `all-MiniLM-L6-v2`, vector(384), chunk/version/provenance, published/visibility/tenant prefilter before context, final permission recheck, citations, poisoned document treated as plain text; no model-driven arbitrary retrieval. **Unit:** chunker/token budget, filter builder. **Integration:** actual embedding and `<=>` pgvector query; cross-tenant and Leila/Maya ACL. **Commands:** `pytest tests/integration/test_rag.py tests/security/test_poison.py -q`. **DoD:** real embeddings/real pgvector, no external key, restricted text absent from captured context.

**Codex prompt:**
> Implement Phase 4 only. Build repeatable Markdown ingestion, local real embeddings, tenant- and role-filtered pgvector retrieval, citations, provenance and a safe policy tool. Test with real vector SQL and poison document. Unauthorized text must never be sent to the LLM context. Do not implement generic agent orchestration yet. Run and report tests, stop.

## Phase 5 — Structured SQL HR tools

**Objective:** safe non-RAG balances/profiles/history/validation. **Files:** `backend/app/tools/leave.py`, `backend/app/services/leave.py`, `backend/app/api/leave.py`, `backend/app/repositories/leave.py`, `backend/tests/integration/test_hr_tools.py`. **Dependencies:** phases 2–3. **Tasks:** authorized own-balance query, history pagination, date validation, explicit weekday-only demo convention, overlap checks; do not yet modify balances. **Unit:** days calculation, validation boundaries. **Integration:** Maya 12/Ravi 5; other-user ID denied, SQL injection harmless. **Commands:** `pytest tests/integration/test_hr_tools.py -q`. **DoD:** all reads source from SQL and are scoped to server actor.

**Codex prompt:**
> Implement Phase 5 only. Implement typed self-only HR read/validation tools with authorized SQLAlchemy queries, predictable errors and tests for 12/5 balances. Include weekday-only leave calculation as an explicit fictional demo convention. No booking writes yet. Run tests and stop.

## Phase 6 — Multi-intent planner and executor

**Objective:** one request can produce several subtask results. **Files:** `backend/app/agent/{llm_protocol.py,fake_llm.py,planner.py,executor.py,tool_registry.py,state.py}`, `backend/app/api/conversations.py`, `backend/tests/unit/test_planner.py`, `backend/tests/integration/test_multitask.py`. **Dependencies:** phases 4–5. **Tasks:** typed intents, dependency DAG, tool allowlist, structured outputs, concurrent independent reads, sequential validation/proposal path, deterministic fake LLM, trace of all subtasks and insufficient-source behavior. **Unit:** intent parser and DAG. **Integration:** triple-intent request yields balance + policy + clarification/leave draft; poison attempts cannot invoke forbidden tool. **Commands:** `pytest tests/unit/test_planner.py tests/integration/test_multitask.py -q`. **DoD:** honest multi-tool execution, no separate autonomous agents needed.

**Codex prompt:**
> Implement Phase 6 only. Build minimal typed planner/executor and LLM protocol with deterministic FakeLLM. Execute independent authorized reads in parallel; preserve subtask results, tool statuses and original request. No task mid-run editing yet; no unapproved writes. Run tests and stop.

## Phase 7 — Proposal/confirmation transaction

**Objective:** human approval as sole booking trigger. **Files:** `backend/app/services/leave.py`, `backend/app/api/leave.py`, `backend/app/repositories/leave.py`, `backend/tests/integration/test_confirm.py`, `backend/tests/security/test_proposals.py`. **Dependencies:** phases 2,3,5,6. **Tasks:** create proposal without leave mutation; owner-only confirm/cancel; expiry and version, `FOR UPDATE`, balance re-check, overlap, append-only history, audit, unique booked proposal ID. **Unit:** state transitions. **Integration:** before confirm unchanged, after confirm one row + correct debit, duplicate and concurrent 409, foreign user/expired denied. **Commands:** `pytest tests/integration/test_confirm.py tests/security/test_proposals.py -q`. **DoD:** no balance/request mutation before explicit confirmed HTTP action.

**Codex prompt:**
> Implement Phase 7 only. Create action proposal state machine and transactional confirm/cancel endpoints. Confirm must derive current actor from auth, lock proposal and balance, revalidate and be exactly-once. Add race, stale, expiry, duplicate and cross-tenant tests. Never let the LLM perform confirmation. Run tests, stop.

## Phase 8 — Persistent running tasks and mid-run notes

**Objective:** update same running task. **Files:** `backend/app/tasks/{runner.py,recovery.py}`, `backend/app/repositories/tasks.py`, `backend/app/api/tasks.py`, `backend/app/agent/{planner.py,executor.py,state.py}`, `backend/tests/integration/test_midrun.py`. **Dependencies:** phases 6–7. **Tasks:** immutable `original_request`, serialized append-only notes and revision, DB leases, checkpoints before/after tools and before generation, late notes replan unfinished work, optional cancel-and-restart generation, no repeated writes, recovery on process restart. **Unit:** note merge/conflicts/dedup. **Integration:** paused fake LLM receives note while task active and produces revised output under same task ID; concurrency and restart checks. **Commands:** `pytest tests/integration/test_midrun.py -q`. **DoD:** true in-flight task update, not a second chat and not a sequential simulation.

**Codex prompt:**
> Implement Phase 8 only. Add persistent task runner, original request retention, append-only mid-run notes, instruction revision and safe checkpoint replanning. Use a controllable pause in FakeLLM for concurrency integration tests. Handle conflicts, cancellation, leases and restart recovery without duplicate operations. Prove the same task ID throughout. Run tests, stop.

## Phase 9 — Event persistence and SSE

**Objective:** live progress, replay and reconnection. **Files:** `backend/app/stream/events.py`, `backend/app/api/tasks.py`, `backend/tests/integration/test_sse.py`. **Dependencies:** phase 8. **Tasks:** event table seq allocation, status/tool/delta/proposal events, heartbeat, replay after seq, terminal event, disconnection handling, ownership check. **Unit:** reducer/event serializer. **Integration:** reconnect after event N, assert correct ordered replay, no duplicate writes, cross-tenant subscription forbidden. **Commands:** `pytest tests/integration/test_sse.py -q`. **DoD:** SSE tests pass using API client and persisted events.

**Codex prompt:**
> Implement Phase 9 only. Persist typed task events and expose authenticated SSE stream with monotonic IDs, `Last-Event-ID` replay, heartbeats and explicit terminal states. Include replay/duplicate/multiple-subscriber tests. Do not build frontend yet. Run tests and stop.

## Phase 10 — React interactive UI

**Objective:** professional but functional demo. **Files:** `frontend/src/{main.tsx,app/App.tsx,pages/*,components/*,hooks/useTaskStream.ts,api/*,styles/global.css}`, `frontend/{package.json,tsconfig.json,vite.config.ts,Dockerfile}`. **Dependencies:** phases 3,8,9. **Tasks:** login, workspace header with tenant+role, chat sidebar, source references, streaming text, tool activity, always-enabled composer routing active messages to `/instructions`, proposal approve/cancel card, reconnect state, accessible loading/error/empty states, small screen layout. **Unit:** component state/event reducer; **integration:** Playwright/browser user flow and API-backed SSE. **Commands:** `npm ci`, `npm run typecheck`, `npm run build`, optional `npx playwright test`. **DoD:** user can send in-flight note via UI and see same task, click confirm without hidden writes.

**Codex prompt:**
> Implement Phase 10 only. Build React/Vite/TypeScript login and tenant workspace, a Cursor-like chat, event reducer for SSE, tool activity and approval cards. Keep composer enabled during running tasks and send notes to existing task endpoint. Display permission errors gracefully. Run typecheck/build and a smoke test, stop.

## Phase 11 — End-to-end integration and adversarial audit

**Objective:** prove assignment behavior. **Files:** `backend/tests/{integration/*,security/*}`, `scripts/verify_demo.sh`, `docker-compose.yml`, targeted bugfixes only. **Dependencies:** phases 0–10. **Tasks:** run security matrix T01–T30, particularly actual pgvector, poison/context test, mid-run concurrency and transaction race; inspect logs for PII; test clean Docker startup and restart. **Unit:** missing edge cases. **Integration:** all critical flows across API/UI. **Commands:** `docker compose up --build -d`, `pytest -q`, `ruff check .`, `npm run typecheck && npm run build`. **DoD:** reproducible end-to-end functionality and accurately documented failures.

**Codex prompt:**
> Implement Phase 11 only. Execute the test matrix, diagnose failures and fix scoped issues without reducing requirements or bypassing tests. Verify keyless real embedding/pgvector tests and poisoned-context isolation. Report command output, known limitations, and stop.

## Phase 12 — README, demo and submission

**Objective:** honest, self-contained reviewer handoff. **Files:** `README.md`, `docs/07_README_and_Checklist.md` references, `.env.example`, `scripts/verify_demo.sh`; minor fixes only. **Dependencies:** phase 11. **Tasks:** quickstart, architecture, schema/flow, seeded actors, use cases, injection handling, tenant strategy, why SQL vs RAG, mid-run internals, approvals, separate DB recommendation, skipped items, actual tracked engineering hours. Screenshots optional. **Unit/integration:** clean checkout dry-run and smoke scenario. **Commands:** `git status`, `docker compose up --build`, `pytest -q`, `npm run build`. **DoD:** README short enough for evaluator, complete deliverables, honest runtime/test evidence.

**Codex prompt:**
> Implement Phase 12 only. Audit deliverables against the original two-page assignment. Write a concise README with exact commands, demo scenarios, architectural judgments, tests, skipped work and **actual hours spent from developer log** (do not invent). Verify a clean-run setup, report evidence and stop.

## 3. Step-by-step supervision

After each phase, independently check: (a) requested files actually exist; (b) logs show tests actually executed; (c) unauthorized access blocked in repositories rather than prose; (d) no stage silently trades away mid-run, RAG or confirmation requirements; (e) any changed architecture decision is recorded. Commit after a green phase with a descriptive conventional message (`feat: add real pgvector retrieval`). Phase prompts should be pasted separately; don't give Codex one giant “implement project” request.
