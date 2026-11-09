# Phase 12 — assignment audit and clean-run evidence

Date: 2026-11-09. Source of truth: both pages of
[Task-AI-Engineer 1.pdf](../assignment/Task-AI-Engineer%201.pdf), extracted and
visually reviewed. The eight blueprint documents are design guidance, not proof
of delivery. Phase 12 changes documentation, the example UI origin and a
source-only verification helper; it adds no product phase or live LLM adapter.

## Deliverables against the PDF

| PDF requirement | Finding and evidence |
| --- | --- |
| Python, Postgres/pgvector, simple chat, Compose (p. 1) | Present: `backend/`, migrations, `frontend/`, `docker-compose.yml`. The `ui` Compose profile must be enabled; migration/seed/index commands precede application startup. |
| Stream and accept extra instructions on the same ongoing job; preserve original request (p. 1) | Persisted SSE, append-only notes/revisions, immutable original text, lease/revision-fenced checkpoints and UI routing are present. The real browser smoke pauses FakeLLM and proves one task ID. Answer chunks follow completed composition; there is no live token provider. |
| Multiple subtasks from one message (p. 1) | Typed DAG planner/executor runs independent authorized reads concurrently and retains partial results. A generic “multi-agent” label is not used as evidence. |
| Propose before booking; confirm before changing data (p. 1) | Proposal metadata can persist, but leave requests/debits do not exist until explicit authenticated confirmation. Transaction locks, version/expiry checks, uniqueness and audit/history protect commits. Browser and real-DB race/rollback tests prove this distinction. |
| Exact identities and tenant boundary (p. 1) | Seeded Maya/Summit employee, Leila/Summit HR and Ravi/Pebble employee. Server-derived actor scope applies to repository queries before content reaches model context. Leila cannot access Pebble. |
| Exact policies and CEO ACL (p. 1) | Summit third late arrival → one-day pay cut; Pebble → warning only. CEO salary-band document is Leila-only. No monetary band or complete handbook was supplied; no numeric salary is fabricated. |
| Poison is a normal Summit source, never obeyed (p. 1) | Original poisoned policy is seeded and retrieved as untrusted data. Captured-context tests prove protected source canaries are absent for unauthorized actors. A separate fictional test directive reaches the model spy without dispatching a booking tool. |
| SQL balances Maya 12 / Ravi 5 (p. 2) | Seeded in `leave_balances`, queried through authorized SQL, not embeddings. Leila has no invented balance. These are initial balances, not values to reset after real demo confirmations. |
| README approach, recommendations, separate-DB option and skipped work (p. 2) | The replacement README covers search/talk/refuse, authorization, notes, transactions, injection boundaries, keep/change judgments and server-controlled routing to existing separate tenant DBs. It discloses demo/production limits. |
| Tests with real embeddings/pgvector and no API key (p. 2) | Local pinned MiniLM and real `<=>` SQL, positive/negative ACL cases, concurrent notes, booking races, restart, SSE and browser tests. Tests use FakeLLM as allowed by the assignment. See the Phase 11 matrix and final Phase 12 outputs below. |
| Live demo LLM (p. 2: any LLM may be used) | Only deterministic FakeLLM is shipped. There is no live-provider adapter/general language understanding. This is disclosed, not claimed as a completed live-model integration. |
| Actual hours spent (p. 2) | **11 hours, developer-reported.** The developer supplied the total during this audit: first day 3 hours, later work described as 2-hour sessions. Recorded in `developer_time_log.md`; no dates or independently timed daily entries were supplied. |
| What to send: README, Compose, seed, tests, streaming UI (p. 2) | All exist in the working tree. Git status still marks implementation files untracked; the sole existing commit is the blueprint. Submission must include these source files, not just that commit. No commit or remote publication is performed here. |

## Actual-hours evidence

The repository was searched for time logs, developer/work logs, timesheets and
hours records, including hidden source files but excluding dependency/cache
contents. The only relevant statement was the previous README's “Actual
engineering hours have not been tracked,” preserved in
[phase history](phase_history.md). At the initial search, no developer-log file was found among the
deliverables. Git has one blueprint commit; neither its timestamp nor
file times establish active development duration. Prior test timings measure
process execution, not engineering hours. The user was asked for the missing
log/verified total while other work continued.

The developer subsequently supplied the explicit total **11 hours**, with 3 hours
on the first day and later work described as 2-hour sessions. The verbatim source
and its limits are recorded in [the developer time log](developer_time_log.md).
The README uses that reported total. It does not claim an automated timer export,
independent verification, or invented calendar dates/per-session entries.

## Clean-run method

`scripts/verify_phase12_clean.py` copies the runnable source/configuration,
assignment and documentation to a temporary snapshot. It explicitly excludes
the current `.env`, `.git`, virtual environment, Node modules, build output and
model caches. It runs the isolated Docker verifier from the snapshot, so the
project uses fresh named volumes, generated credentials and free host ports.
The host Python interpreter is only the verification driver; application
dependencies and the real local model are provided by the built containers.

The sequence matches the README: build API/UI → start DBs → migrate → seed →
index real policies → start UI/API → authenticate and query. It then checks
persisted task/SSE replay after restart, session invalidation, real DB-outage
recovery, and body/query secret-canary absence in logs. All disposable
containers/volumes and the source snapshot are cleaned up. Existing development
data and `.env` remain untouched.

Docker build cache is allowed; this is a source-only/fresh-volume test, not a
claim that every dependency was redownloaded or that the host has no Docker/Python
cache. Initial builds require network access for dependencies/public model
weights. Runtime/tests use local embeddings without cloud LLM credentials.

## Changes and limits

- Replaced the historical, phase-by-phase README with a concise evaluator
  handoff; retained earlier outputs separately in `docs/phase_history.md`.
- Aligned `.env.example`'s default origin with the UI on port 5173. The existing
  local `.env` was preserved. The README passes the seed password explicitly
  through the shell environment rather than assuming Compose injects it.
- Added a source-only clean-run helper and this audit. No backend/UI behavior or
  assignment facts changed.
- Live-provider/token streaming, distributed auth, production deployment,
  advanced natural-language orchestration, real holiday rules and independently timed
  engineering-hour records remain absent; the supplied 11-hour total is attributed
  to the developer. Cold synchronous model startup can exceed
  a 20-second client timeout; the normal asynchronous UI task flow is verified.

Verification command results are recorded below. Historical security
evidence remains in [the Phase 11 report](phase11_verification.md).


## Observed Phase 12 results

| Command/check | Observed result |
| --- | --- |
| Original PDF inspection | Both pages extracted and rendered; original identity/policy/balance facts, deliverable list and README/hour requirements visually reviewed. |
| `.\.venv\Scripts\python.exe scripts/verify_phase12_clean.py` | Exit 0; source-only Docker build/start/migrate/seed/index, UI proxy, keyless policy retrieval, restart/SSE persistence, real DB-outage recovery and log canary checks all passed. Snapshot and disposable volumes removed. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_seed.py backend/tests/security/test_poison.py backend/tests/integration/test_frontend.py` | Exit 0: **`16 passed, 1 warning in 57.57s`**, no skips. Real local embeddings/pgvector, exact seed facts and a headless real-browser note/approval flow. |
| `npm.cmd run typecheck` (frontend) | Exit 0; no TypeScript errors. |
| `npm.cmd test` (frontend) | Exit 0; **6 passed**, 0 failed/skipped. Existing Node 22 type-stripping warning. |
| `npm.cmd run build` (frontend) | Exit 0; Vite 7.3.7, 32 modules, built in **1.22s**; JS 239.36 kB / 75.20 kB gzip, CSS 9.65 kB / 2.94 kB gzip. |
| `ruff check backend scripts` / `ruff format --check backend scripts` | `All checks passed!` / **92 files already formatted**. |
| `python -m pip check` | `No broken requirements found.` |
| Git Bash `bash -n scripts/verify_demo.sh` | Exit 0. |
| README/audit local-link check | All local targets exist. |
| `git diff --check` | Exit 0. Source remains untracked; no commit/publish performed. |

Clean-run output:

```text
Phase 12: source-only snapshot; no .env, host dependencies or model cache copied
Docker: api + frontend images built
Docker: clean isolated startup, migrations, seed and real local index passed
Docker: UI proxy, keyless policy SQL, restart/SSE persistence and real DB-outage recovery passed
Docker: logs contain no tested password/session-secret/request canaries
{"project": "phase11_84e933277c684122a2339cbfce82cc71", "result": "passed", "persistent_dev_data": "untouched"}
Phase 12: source-only clean-run passed; Docker build cache permitted; temporary source removed
```

The existing Starlette/httpx warning remains. The earlier full Phase 11 result
(**338 passed, 1 warning**) is historical evidence, not described as a newly
rerun full Phase 12 suite. The only added inspection dependency was a PDF reader
in an ignored temporary directory; no application dependency/configuration secret
or persistent database was changed. No dated engineering sessions were invented:
the README's **11 hours** is attributed to the developer's supplied statement.
