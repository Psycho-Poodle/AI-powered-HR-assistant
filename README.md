# HR Chat Assistant

A tenant-scoped HR chat demo for Summit Dental and Pebble Retail. Python/FastAPI,
PostgreSQL + pgvector, React/TypeScript, persisted task execution and SSE.
The Docker demo defaults to **Google Gemini (`gemini-3.6-flash`)**, with optional
**OpenAI Responses API (`gpt-5.4-mini`)** support. Automated tests
explicitly select deterministic FakeLLM and never require an external API key.

## Run the demo

Requires Docker with Linux containers and Compose. Initial builds download
dependencies and pinned CPU embedding weights. Embeddings remain local; live
planning and answers require the selected provider's network access and API key.
Run from the repository root.

PowerShell (preserves an existing `.env`):

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env`: choose **different URL-safe hexadecimal** `POSTGRES_PASSWORD` and
`TEST_POSTGRES_PASSWORD`, set a random `SESSION_SECRET` of at least 32 characters,
`APP_ORIGIN=http://localhost:5173`, and `SESSION_COOKIE_SECURE=false` for local
HTTP only. Existing volumes require their original database credentials.

For the real demo, edit the ignored local `.env` in your editor:

```dotenv
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.6-flash
GEMINI_API_KEY=<your local Gemini API key>
```

Never put the key in frontend variables, Git, screenshots or chat. To run a
keyless manual demo instead, set `LLM_PROVIDER=fake`. Compose defaults to `gemini`;
direct host Python defaults to `fake` unless explicitly configured through its
environment (host settings do not automatically read `.env`). Missing live
credentials produce a task error; the server never silently switches providers.

Create a Gemini key in [Google AI Studio](https://aistudio.google.com/api-keys).
Model/quota access depends on your Google project; free quota is not unlimited.
To select OpenAI instead, set `LLM_PROVIDER=openai`,
`OPENAI_MODEL=gpt-5.4-mini` and `OPENAI_API_KEY` in the same local `.env`.
Both keys may coexist; only the selected provider receives requests. Recreate
the API after changing provider settings; there is no automatic paid fallback.

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
For an existing seeded installation, skip seeding/migration/index steps unless
needed; apply a provider change with `docker compose --profile ui up -d --build api frontend`.
After signing in, the header shows the configured provider/model. A completed
task's authenticated `GET /api/v1/tasks/{id}` exposes
`plan.execution.provider`, `model` and `usage` (calls/input/output tokens).
Verify `gemini` (or explicitly selected `openai`), the model and successful usage;
a badge alone
does not prove a successful provider call. `/api/v1/runtime` reports configuration
only and never returns the key.
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
   balance. Only Leila can retrieve Summit's fictional CEO salary-band document.
   Its demo amounts were not supplied by the assignment. She still cannot access Pebble.
3. Maya: **"Tell me my remaining leaves, explain the late attendance policy,
   and prepare a leave request for three days."** Inspect separate tool results;
   missing dates are clarified. Send **"Use plain language"** while running:
   same task ID, original retained. Fast tasks may finish first; a controllably
   paused browser test proves genuine overlap.
4. Only an explicit request such as **"Help me apply for leave"** opens the date
   form. Greetings, balances, policies and ambiguous questions do not. A dated
   follow-up can continue an initiated workflow in the same conversation.
   Choose future Monday-Wednesday dates. **Prepare proposal**
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
  tests and approvals. Add SSO/distributed sessions, least-privilege DB
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

The driver strips `OPENAI_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY`, and sets
`LLM_PROVIDER=fake` in the test subprocess. The suite blocks real OpenAI/Google
transport; SDK tests use
`httpx.MockTransport`. Docker verification also explicitly chooses fake. Local
embedding weights must first be downloaded; subsequent vector tests run offline.
Run lint with `.\.venv\Scripts\python.exe -m ruff check backend scripts` and
frontend formatting with `cd frontend; npm.cmd exec -- prettier --check src tests package.json`.

Live errors are shown in the chat: missing key/authentication means configure
the local key and recreate the API container; model-access errors mean check
`GEMINI_MODEL` / `OPENAI_MODEL` and your account's model access. Temporary request/token rate
limits require waiting; `provider_quota_exhausted` requires checking OpenAI API
billing, available credit and applicable usage limits. `credit_balance_exhausted`
is not fixed by repeatedly retrying. Network/timeout errors mean check API connectivity/proxy/firewall
and optionally `GEMINI_TIMEOUT_SECONDS` / `OPENAI_TIMEOUT_SECONDS`. Invalid or oversized output/context
fails the task visibly. No provider failure creates a booking or fake answer.
Never paste raw environment/configuration or provider responses into reports.
Provider architecture and limits: [ADR 0012](docs/adr/0012-openai-provider-and-intent-workflows.md).
Gemini provider/default and current verification: [ADR 0013](docs/adr/0013-gemini-provider.md).

Optional **paid, external** SDK-only smoke (not part of the offline suite):
`.\.venv\Scripts\python.exe scripts/verify_live_llm.py`. It reads the ignored local
`.env`, sends a greeting without HR records, and reports provider/model/usage;
it does not verify browser wiring. Verify a live browser task separately using
the task metadata described above. No live call is claimed without success.

The earlier Phase 12 clean-run passed from a source-only snapshot and fresh Docker
volumes. Its historical details and exclusions are in the audit linked below.
Current provider/workflow changes and exact verification outputs are recorded in
[Gemini verification](docs/gemini_verification.md), with the earlier OpenAI
results in [live integration verification](docs/live_llm_verification.md).

Last Phase 11 full result: **338 passed, 1 warning**, no skips; frontend **6 passed**,
typecheck/build passed, clean npm install audited **0 vulnerabilities**. See the
[T01-T30 matrix and outputs](docs/phase11_verification.md) and the
[assignment audit / clean-run evidence](docs/phase12_submission_audit.md).

## Limits, skipped work and hours

Skipped: enterprise SSO,
production deployment, upload UI/virus scanning, payroll/HRIS integration, real
holiday rules, Python lockfile and immutable image digests. Tool progress is live;
answer chunks follow completed composition. Cold synchronous search exceeded a
20-second timeout in audit; the async task path handles model initialization.
API restart requires login; sidebar history resets on refresh.

A DB outage delays durable status until recovery; uncheckpointed reads may retry,
but confirmed writes are not autonomously replayed. Packaged access logs redact
queries; local Uvicorn needs `--log-config backend/logging.json` with
`--app-dir backend`. Canary checks are not universal PII guarantees. Additional
policies and the supplementary CEO salary band are labeled fictional; the original
assignment provided neither a complete handbook nor a CEO monetary figure.

**Actual engineering hours: 25 hours, developer-reported.** First day: 4 hours;
subsequent work was described as 3-hour sessions. See the
[developer time record](docs/developer_time_log.md). Dates and individual later
entries were not supplied; no timestamp-based estimate is substituted.

Source: [original two-page assignment](assignment/Task-AI-Engineer%201.pdf).
Design rationale: [ADRs](docs/adr/). Earlier execution evidence is archived in
[phase history](docs/phase_history.md). The complete implementation is included
on this feature branch. Earlier audit notes describe the pre-publication working tree.
