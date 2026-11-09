# HR Chat Assistant

A tenant-scoped HR chat demo for Summit Dental and Pebble Retail. Python/FastAPI,
PostgreSQL + pgvector, React/TypeScript, persisted task execution and SSE.
**The shipped demo uses deterministic FakeLLM, not a live LLM provider.**

## Run the demo

Requires Docker with Linux containers and Compose. Initial builds download
dependencies and pinned CPU embedding weights; runtime is local/keyless.
Run from the repository root.

PowerShell (preserves an existing `.env`):

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env`: choose **different URL-safe hexadecimal** `POSTGRES_PASSWORD` and
`TEST_POSTGRES_PASSWORD`, set a random `SESSION_SECRET` of at least 32 characters,
`APP_ORIGIN=http://localhost:5173`, and `SESSION_COOKIE_SECURE=false` for local
HTTP only. Existing volumes require their original database credentials.

```powershell
docker compose --profile ui config -q
docker compose --profile ui build api frontend
docker compose up -d --wait db db_test
docker compose run --rm api alembic upgrade head
$env:DEMO_SEED_PASSWORD = Read-Host 'Choose the shared demo login password'
docker compose run --rm -e DEMO_SEED_PASSWORD api python -m app.seed.load_seed --seed-dir /seed
Remove-Item Env:DEMO_SEED_PASSWORD
docker compose run --rm api python -m app.rag.index_seed
docker compose --profile ui up -d --wait
```

Open **http://localhost:5173**. All three accounts use the password chosen above.
Configurable ports: `FRONTEND_PORT=5173`, `API_PORT=8000`, `POSTGRES_PORT=5432`,
`TEST_POSTGRES_PORT=5433`. `APP_ORIGIN` must match the exact UI origin. Nginx
proxies `/api` without SSE buffering. Use HTTPS/secure cookies outside local
HTTP. Seed/index commands are repeatable and do not reset used balances.
`docker compose --profile ui down` stops the demo while retaining its volumes.

POSIX shells use the same Docker commands; replace the PowerShell password lines
with `read -rs DEMO_SEED_PASSWORD; export DEMO_SEED_PASSWORD` and
`unset DEMO_SEED_PASSWORD` after seeding.

## Review scenarios

| Login | Company / role | Initial own leave |
| --- | --- | --- |
| maya | Summit Dental / employee | 12 days |
| leila | Summit Dental / HR | Not supplied |
| ravi | Pebble Retail / employee | 5 days |

All accounts use your chosen seed password.

1. Ask **"Explain the late attendance policy."** Maya gets Summit's one-day pay
   cut; Ravi gets warning only. Both are the rule for being late three times.
2. **"My remaining leave balance"** returns 12/5 from SQL. Leila has no invented
   balance. Only Leila can retrieve Summit's CEO salary-band document; no pay
   amount was supplied. She still cannot access Pebble.
3. Maya: **"Tell me my remaining leaves, explain the late attendance policy,
   and prepare a leave request for three days."** Inspect separate tool results;
   missing dates are clarified. Send **"Use plain language"** while running:
   same task ID, original retained. Fast tasks may finish first; a controllably
   paused browser test proves genuine overlap.
4. Choose future Monday-Wednesday dates on a completed task. **Prepare proposal**
   leaves bookings/balance unchanged; **Confirm booking** books once (untouched
   Maya: 12 to 9). Cancel is separate. Counting inclusive weekdays is an explicit
   **fictional demo convention**, without a verified holiday calendar.
5. The poisoned Summit policy remains searchable. Captured-context tests prove
   its instructions cannot disclose protected sources or dispatch booking tools.

## Approach and judgments

- **Isolation / routing:** login derives immutable actor scope. Parameterized SQL
  enforces company, visibility and self-access before model context. Policies use
  real MiniLM vectors (384 dimensions) and filtered pgvector cosine search;
  balances/history use SQL. The typed planner chooses reads, talk, clarification
  or refusal. Retrieved text cannot grant permissions or call tools. RLS adds
  protection, but the trusted service credential can bypass it.
- **Notes / stream:** reads run concurrently; PostgreSQL retains original requests,
  append-only notes/revisions, checkpoints, leases and events. Safe-boundary
  replanning and final revision/lease checks reject stale answers. SSE IDs enable
  replay; the UI deduplicates and reconnects.
- **Writes:** proposals store intent only. Explicit confirmation locks and
  revalidates owner/version/expiry/dates/overlap/balance, then atomically commits
  booking, debit, history and audit. Locks/uniqueness prevent duplication and
  overdraw; no transaction waits open for human approval.
- **Recommendations:** keep the monolith, typed tools, SQL authorization, real-vector
  tests and approvals. Add live LLM, SSO/distributed sessions, least-privilege DB
  roles, rate limits, monitoring and backups. For existing separate company DBs,
  route authenticated tenants through a server-controlled registry to separate
  credentials/pools and migrations/backups; avoid cross-DB HR joins. Stronger
  isolation costs more operations.

## Test and verification

Host tests require Python 3.12, Node 22.14+ and the documented Docker databases.
PowerShell setup (use `.venv/bin/python`, `npm` and `npx` on POSIX):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
.\.venv\Scripts\python.exe -m app.rag.embeddings --download
cd frontend
npm.cmd ci
# Windows smoke uses installed Edge; otherwise install Chromium:
# npx.cmd playwright install chromium
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe scripts/verify_phase2.py
.\.venv\Scripts\python.exe scripts/verify_phase11_docker.py
```

The first driver runs all backend/security/browser tests in disposable DBs with
real offline embeddings/pgvector. The second builds a separate Compose project
with generated credentials, fresh volumes and free ports, then verifies startup,
indexing, UI proxy, restart/replay, DB recovery and log canaries before cleanup.
Neither resets configured databases. Git Bash/Linux also supports
`bash scripts/verify_demo.sh --docker`.

Phase 12 clean-run: **passed** from a source-only snapshot and fresh Docker
volumes. Current focused checks: **16 passed, 1 warning**; frontend **6 passed**;
typecheck/build passed. Details and exclusions are in the audit linked below.

Last Phase 11 full result: **338 passed, 1 warning**, no skips; frontend **6 passed**,
typecheck/build passed, clean npm install audited **0 vulnerabilities**. See the
[T01-T30 matrix and outputs](docs/phase11_verification.md) and the
[assignment audit / clean-run evidence](docs/phase12_submission_audit.md).

## Limits, skipped work and hours

Skipped: live-provider/general language understanding, enterprise SSO,
production deployment, upload UI/virus scanning, payroll/HRIS integration, real
holiday rules, Python lockfile and immutable image digests. Tool progress is live;
answer chunks follow completed composition. Cold synchronous search exceeded a
20-second timeout in audit; the async task path handles model initialization.
API restart requires login; sidebar history resets on refresh.

A DB outage delays durable status until recovery; uncheckpointed reads may retry,
but confirmed writes are not autonomously replayed. Packaged access logs redact
queries; local Uvicorn needs `--log-config backend/logging.json` with
`--app-dir backend`. Canary checks are not universal PII guarantees. Additional
policies are labeled fictional; no complete handbook or CEO monetary figure
was provided.

**Actual engineering hours: 11 hours, developer-reported.** First day: 3 hours;
subsequent work was described as 2-hour sessions. See the
[developer time record](docs/developer_time_log.md). Dates and individual later
entries were not supplied; no timestamp-based estimate is substituted.

Source: [original two-page assignment](assignment/Task-AI-Engineer%201.pdf).
Design rationale: [ADRs](docs/adr/). Earlier execution evidence is archived in
[phase history](docs/phase_history.md). The complete implementation is included
on this feature branch. Earlier audit notes describe the pre-publication working tree.
