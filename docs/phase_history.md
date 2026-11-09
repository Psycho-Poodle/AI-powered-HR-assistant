# HR Chat Assistant

Phases 0-11 are implemented: FastAPI, Docker infrastructure, the 15-table schema,
Alembic migrations, demo authentication, authorized policy retrieval, and typed
self-only HR reads/advisory leave validation, and a typed planner/executor with FakeLLM.
Owner-confirmed leave booking, durable task recovery and mid-run instructions
are implemented. Authenticated persisted SSE and a React tenant workspace are
implemented.
Source requirements remain in docs 01-08 and
`assignment/Task-AI-Engineer 1.pdf`.

## Run with Docker

Requires Docker Desktop using Linux containers. From the repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: set different POSTGRES_PASSWORD and TEST_POSTGRES_PASSWORD values.
# Use random URL-safe hexadecimal passwords. Preserve an existing .env.
# Also set a random SESSION_SECRET of at least 32 characters.
# Set SESSION_COOKIE_SECURE=false only for the local HTTP demo.
docker compose config --quiet
docker compose up -d --wait db db_test
docker compose up -d --build --wait api
```

Host ports are configurable through `POSTGRES_PORT` (default 5432),
`TEST_POSTGRES_PORT` (5433), and `API_PORT` (8000). All bind to `127.0.0.1`.
Ports 5432/5433 are now available and are used by the local `.env` and test runner.
Container connections always use `db:5432`, independent of host ports.
`GET http://127.0.0.1:8000/api/v1/health/live` returns HTTP 200
`{"status":"ok"}` with the default API port.

The API runs as a non-root user and requires `DATABASE_URL` from its environment.
Startup checks `SELECT 1` and the installed vector extension; a failed check
prevents startup. Liveness itself does not query dependencies on each request.
Settings reject missing URLs, unsupported driver schemes and missing DB names.
Compose supplies the API URL and auth configuration; Python does not automatically
read `.env`. The Phase 2 migrations and seed must be applied before logging in.

Dev and test have separate containers, named volumes, networks, names and
credentials. The API joins only the dev network. The init SQL creates only
`vector`, and runs only on fresh data directories. Existing volumes retain their
initial database names and credentials when `.env` changes. `docker compose stop`
stops services without deleting data. Never use `down -v` on data you need.

## Tests and lint

Requires Python 3.12+. Create a virtual environment and install the backend:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
```

If the Windows launcher does not discover Python 3.12, invoke its installed
executable directly. With both databases healthy, configure host test URLs from
the simple unquoted `.env` format shown in `.env.example`:

```powershell
$phase1Config = Get-Content -Raw .env | ConvertFrom-StringData
$devPass = [uri]::EscapeDataString($phase1Config.POSTGRES_PASSWORD)
$testPass = [uri]::EscapeDataString($phase1Config.TEST_POSTGRES_PASSWORD)
$env:DEV_DATABASE_URL = "postgresql://$($phase1Config.POSTGRES_USER):${devPass}@127.0.0.1:$($phase1Config.POSTGRES_PORT)/$($phase1Config.POSTGRES_DB)"
$env:TEST_DATABASE_URL = "postgresql://$($phase1Config.TEST_POSTGRES_USER):${testPass}@127.0.0.1:$($phase1Config.TEST_POSTGRES_PORT)/$($phase1Config.TEST_POSTGRES_DB)"
.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests -q -s -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m pip check
```

Unit-only: replace `backend/tests` with `backend/tests/unit`. The live integration
test skips explicitly if either URL is absent; configured connection failures
fail the test. It uses real PostgreSQL: extension lookup, cosine SQL, different
database names/users/system identifiers, and zero public tables. Cluster identifier
access requires the local bootstrap users. Least-privilege tenant authorization
belongs to later phases. For host API development set `DATABASE_URL` to the dev
URL and run `python -m uvicorn app.main:app --app-dir backend --reload` in the venv.

## Observed Phase 1 verification (2026-11-07)

Python 3.12.10, psycopg 3.3.8, pydantic-settings 2.16.2, pytest 8.4.2,
Ruff 0.17.3; PostgreSQL image `pgvector/pgvector:0.8.0-pg16`.

| Command | Observed result |
| --- | --- |
| `docker compose config --quiet` | Exit 0. |
| `docker compose up -d --wait db db_test` | Both healthy after changing local host ports to 55432/55433; first attempt failed because Windows blocked port 5432. |
| `docker compose up -d --build --wait api` | Exit 0; image built and API healthy. |
| Full pytest command above | Exit 0: `10 passed, 1 warning in 1.22s`; no skips. |
| `python -m ruff check backend` (venv) | Exit 0: `All checks passed!` after formatting one long line. |
| `python -m ruff format --check backend` (venv) | Exit 0: `9 files already formatted`. |
| `python -m pip check` (venv) | Exit 0: `No broken requirements found.` |
| `docker compose ps` | `api`, `db`, `db_test` healthy. |
| `docker compose exec -T db psql -U hr_dev -d hr_dev -c "SELECT current_database(), extversion FROM pg_extension WHERE extname='vector';"` | `hr_dev`, `0.8.0`. |
| Same SQL via `docker compose exec -T db_test psql -U hr_test -d hr_test` | `hr_test`, `0.8.0`. |
| API HTTP probe inside container | `200 {"status":"ok"}`. |

Integration output: `vector installed and cosine query passed on both;
dev=hr_dev/hr_dev, test=hr_test/hr_test; distinct cluster identifiers;
zero public tables`.

The remaining warning is the existing Starlette TestClient deprecation of
`httpx`. An earlier run also had a Windows pytest-cache permission warning;
the final command disables that optional cache. Docker access and dependency
installation required sandbox escalation. Generated local `.env` is ignored.
Version tags and bounded dependency ranges are used; immutable image digests
and a Python lockfile are deferred.

See [ADR 0001](docs/adr/0001-architecture.md),
[ADR 0002](docs/adr/0002-database-infrastructure.md), and
[ADR 0003](docs/adr/0003-schema-and-seed.md) and
[ADR 0004](docs/adr/0004-demo-auth-and-isolation.md) and
[ADR 0005](docs/adr/0005-local-policy-retrieval.md) and
[ADR 0006](docs/adr/0006-self-only-hr-validation.md) and
[ADR 0007](docs/adr/0007-typed-planner-and-foreground-tasks.md).
Phase 8 requires separate authorization. See also
[ADR 0008](docs/adr/0008-human-confirmed-leave-transactions.md).
Actual engineering hours have not been tracked.

## Phase 2: migrations and seed

Install updated dependencies with the venv pip command above. With a valid
development `DATABASE_URL`, run from the repository root:

```powershell
# DATABASE_URL must use credentials valid for the persistent development cluster.
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
# Set DEMO_SEED_PASSWORD in the process environment; there is no default password.
.\.venv\Scripts\python.exe -m app.seed.load_seed --seed-dir seed
.\.venv\Scripts\python.exe -m app.seed.load_seed --seed-dir seed
```

The first seed inserts 2 companies, 3 users, 2 leave balances and 6 policy sources;
the repeat inserts zero rows. Maya has 12 days, Ravi 5; Leila has no seeded balance.
The CEO source is Leila-only and has no numeric salary. The poisoned Summit
source is untrusted data. The two annual-leave examples are visibly labeled
FICTIONAL DEMONSTRATION DATA. Manifests store access/version/provenance, while
database rows record source SHA-256 and ingestion/publication timestamps.
`policy_chunks` is empty: no embedding or RAG implementation exists yet.

Changed policy content or access metadata conflicts instead of silently
overwriting the same version. Repeated seeding preserves stored password hashes
and current balances. Seed inserts are transactional and use a seed advisory lock.
Migration `0001_schema` creates extensions, tables, constraints and indexes;
`0002_guards` adds tenant RLS, append-only and immutable-field triggers.
RLS is only a tenant boundary here, not Phase 3 visibility/self-record enforcement.
Bootstrap superusers bypass RLS; real tests also use a nonprivileged role.

The Docker image includes Alembic files and Compose mounts source files at `/seed`.
Container equivalents (inherit an already-set shell `DEMO_SEED_PASSWORD`):

```powershell
docker compose build api
docker compose run --rm api python -m alembic -c alembic.ini upgrade head
docker compose run --rm -e DEMO_SEED_PASSWORD api python -m app.seed.load_seed --seed-dir /seed
```

Direct host/API bootstrap needs credentials matching the persistent volume.
The Phase 2 run encountered a password mismatch; verification avoids depending on
those passwords and does not rotate them or delete volumes. The dedicated runner
uses local Docker psql access and temporary test credentials:

```powershell
# Current project ports; alternate ports can still be configured.
$env:POSTGRES_PORT = '5432'
$env:TEST_POSTGRES_PORT = '5433'
docker compose up -d --wait db db_test
.\.venv\Scripts\python.exe scripts/verify_phase2.py --dev-port 5432 --test-port 5433
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

The runner verifies distinct clusters, creates a uniquely named disposable test
database and temporary roles, and removes them on completion. Its dev role is
read-only; all schema/seed tests write only to the disposable test database.
Existing development/test application data is not reset. Migration/seed tests
skip explicitly outside this harness unless its disposable-database environment
is supplied. The Phase 1 cluster test no longer asserts zero public tables,
because Phase 2 now supplies a schema.

Observed Phase 2 results on 2026-11-07:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'` | Exit 0; installed SQLAlchemy 2.1.8, Alembic 1.20.1, pgvector 0.5.1 and argon2-cffi 25.1.0. |
| `docker compose up -d --wait db db_test` with port overrides above | Exit 0; both healthy on 55432/55433. Earlier attempt without overrides failed on Windows port 5432. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `56 passed, 1 warning in 16.45s`; no skips. At Phase 2 verification the defaults were 55432/55433; current defaults are 5432/5433. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `21 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `docker compose build api` | Exit 0; image includes dependencies and Alembic files. Existing API container was not replaced. |
| `git diff --check` | Exit 0. |

Live output included `migrations: empty DB -> head; model/schema match`,
`seed: 2 companies, 3 users, 12/5 balances, 6 policies; repeat is exact no-op`,
and `migrations: head -> base -> head passed`. Tests reject all 19 cross-tenant
FK paths, changed policy versions/access metadata, invalid source paths,
unlabelled fictional policies, missing seed passwords, history mutation,
duplicate event sequences/bookings, invalid balances/dates and immutable-field
changes. A nonprivileged role verifies RLS fails closed and blocks cross-tenant
inserts. The remaining warning is the existing Starlette/httpx deprecation.

Migrations and seed were validated in a disposable database only; they were not
applied to persistent dev/test databases. No authentication or RAG was built.

## Phase 3: authentication and authorization

`POST /api/v1/auth/login` accepts only `username` and `password`, verifies the
seeded Argon2id hash, and returns a signed opaque HttpOnly/SameSite=Strict cookie
plus a session-bound `csrf_token`. Supply `Origin` exactly matching `APP_ORIGIN`
(default `http://localhost:8000`). Passwords come from the Phase 2 seed, not source
code. Unknown or ambiguous usernames and invalid credentials receive the same 401.

`GET /api/v1/me` returns the authenticated identity. Protected dependencies reload
active user/company/role from PostgreSQL and construct a frozen `ActorContext`.
Client company, role and user IDs are never authoritative. Extra JSON/query
fields are rejected and spoofed identity headers/cookies are ignored.

`POST /api/v1/auth/logout` requires an empty body, the exact allowed Origin and
`X-CSRF-Token` from login. It invalidates the server session and clears the cookie.
All protected unsafe methods using `CurrentActor` enforce these Origin/CSRF checks.
Sessions expire after `SESSION_TTL_SECONDS` (default 1800). A fresh login rotates
the current browser session. These are in-memory demo sessions: use one API worker;
restart requires login again. `SESSION_SECRET` has no default and is required
at startup. `SESSION_COOKIE_SECURE` defaults to true; `.env.example` explicitly
sets false for local HTTP. Use true with HTTPS and set `APP_ORIGIN` to the actual
browser origin, including a custom API port when appropriate.

`GET /api/v1/policies/{uuid}` remains an authorized direct source read.
SQL predicates require the actor tenant, published status and allowed visibility:
all employees in that tenant, tenant HR, or the specified user. The CEO source
remains Leila-only. `GET /api/v1/leave/balance` reads only the current user's SQL
record (Decimal days serialized as a string). Scoped profile/history repository
queries were initially repository-only; Phase 5 now adds typed tools and HTTP reads. HR does
not automatically gain another employee's self records. Inaccessible and missing
policy IDs both return non-enumerating 404s. Responses use `Cache-Control: no-store`.

Authenticated transactions set `app.tenant_id` locally. Credential discovery uses
the existing bootstrap DB connection because login precedes tenant identification;
explicit scoped read predicates enforce permissions even when that role bypasses
RLS. A dedicated least-privilege credential lookup and shared durable session
store remain hardening work. Authentication does not depend on model prompts.

The full real-database test command remains:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
```

Despite its historical name, this runs all current backend tests, including
`backend/tests/security/test_isolation.py`. Shared migration/seed fixtures are
now in `backend/tests/conftest.py`. Tests cover permission matrices, Leila/Pebble
denial, SQL injection/forged identity inputs, self-only profile/history/balance,
disabled users/companies, role refresh, cookie flags/tampering/rotation/replay,
expiry and Origin/CSRF validation. Authentication and queries use real PostgreSQL;
only the test transaction lifetime is overridden. Dev/test data remains unchanged.

Observed Phase 3 results on 2026-11-07:

| Command | Observed result |
| --- | --- |
| `docker compose config --quiet` | Exit 0. |
| `docker compose up -d --wait db db_test` | Exit 0; both healthy on 5432/5433. |
| `.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit -q -p no:cacheprovider` | Exit 0: `28 passed, 1 warning in 1.95s`. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `134 passed, 1 warning in 46.23s`; no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `35 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `docker compose build api` | Exit 0; image built. Persistent application schema/seed was not modified or deployed by this run. |
| `docker compose ps` | `db`: `127.0.0.1:5432`, `db_test`: `127.0.0.1:5433`, both healthy. |
| `git diff --check` | Exit 0. |

The single pytest warning remains Starlette TestClient's `httpx` deprecation.
Login, `/me`, protected reads and logout were exercised through FastAPI against
the real disposable PostgreSQL database. Authentication checks do not call an
LLM. The Phase 3 run did not include Phase 4 retrieval work.

## Phase 4: local policy ingestion and retrieval

Prepare the real CPU embedding runtime and pinned model once (network needed):

```powershell
.\.venv\Scripts\python.exe -m pip install 'torch==2.6.0' --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
$env:HF_HUB_DISABLE_XET = '1'
.\.venv\Scripts\python.exe -m app.rag.embeddings --download
```

The model is `sentence-transformers/all-MiniLM-L6-v2`, pinned at
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The host cache defaults to
`.cache/embeddings/<revision>` (ignored by Git); optionally set
`EMBEDDING_MODEL_PATH` to a prepared directory. Runtime verifies file checksums
and loads only local safetensors/config/tokenizer assets, with no API key or
download fallback. Missing or corrupt assets produce an explicit error. Docker
builds cache the model at `/opt/embeddings` and run with offline flags enabled.

With valid `DATABASE_URL` credentials and the Phase 2 seed loaded:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m app.rag.index_seed
.\.venv\Scripts\python.exe -m app.rag.index_seed
```

The second indexing run is a no-op. The trusted administrative CLI indexes
existing published sources; it is not exposed to users or a model. Migration
`0003_rag_provenance` records model/revision/chunker, source hash, index fingerprint
and indexing time. Sources without a current verified index are excluded from
retrieval. Existing seed hashes, ACLs and source documents are preserved.
For a built container use `docker compose run --rm api python -m app.rag.index_seed`
after applying migrations and seed as above.

Authenticated `GET /api/v1/policies/search?q=late&limit=5` returns typed source
chunks with stable citations, source SHA-256/filename, version, provenance and
model identity. The policy tool returns `sources_found` or `insufficient_sources`
and an explicitly untrusted JSON reference payload for a future LLM adapter.
There is no generated answer, LLM call, arbitrary SQL/tool execution or planner.

`POST /api/v1/policies/ingest` accepts JSON from authenticated HR with the existing
Origin and session-bound `X-CSRF-Token` header. Example body (all extra authority
fields are rejected):

```json
{
  "slug": "example-leave",
  "version": 1,
  "title": "Example leave - FICTIONAL DEMONSTRATION DATA",
  "markdown": "# FICTIONAL DEMONSTRATION DATA\nThis is fictional test content, not an actual employer policy.",
  "source_filename": "example-leave.md",
  "visibility": "all",
  "provenance": "fictional_demo"
}
```

Company comes from the server actor. A specific-user recipient must belong to
that company. Source filenames must be Markdown basenames; source size is capped
at 1 MiB. Uploads must be visibly fictional, while assignment provenance is
reserved for controlled seed sources. This phase provides a bounded JSON Markdown
API; the optional multipart upload screen, PDF ingestion and document-management
UI are deferred.

The real tokenizer creates 200-token chunks with 60-token overlap. The initial
blueprint's 400-token suggestion exceeds this model's input window; the smaller
budget avoids silent truncation. Normalized chunk text strips executable markup,
link targets and controls, while the raw UTF-8 source hash remains unchanged.
Identical ingestion preserves chunk IDs/timestamps. Same-version body/ACL changes
return 409; increasing versions publish atomically and retire older published
versions only after indexing succeeds. Failed embedding/index writes roll back.

Exact pgvector cosine SQL ranks a materialized tenant/status/visibility-filtered
set, also checking model/chunker/source identity. A second permission query under
shared policy locks precedes context assembly. Default minimum cosine similarity
0.2 is a demo relevance heuristic, not an access-control mechanism. The poisoned
Summit policy remains untrusted source data; it cannot alter the actor, request
another tenant or execute a tool. Citations are constructed from permitted DB
records, not from instructions or citation claims inside source text.

Run the complete keyless suite after caching the model:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

The existing runner sets Hugging Face/Transformers offline flags and removes
provider API keys for tests. Tests perform real local inference and real pgvector
SQL in a disposable DB, record the exact future-LLM context, and reject forbidden
canary text/IDs even when a forbidden source is the nearest unfiltered vector.
They also cover ACL changes between ranking and final context, stale/unpublished
indexes, provenance, token budgets, repeat ingestion and rollback after model
failure. Persistent development/test data is not reset.

Observed Phase 4 verification on 2026-11-08:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pip install 'torch==2.6.0' --index-url https://download.pytorch.org/whl/cpu` | Exit 0; CPU PyTorch `2.6.0+cpu`. |
| `.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'` | Exit 0; Sentence Transformers 3.4.1, Transformers 4.49.0 and NumPy 2.5.4 installed. |
| Pinned asset preparation | Cached 10 files at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; the existing host downloader prepared the same manifest while project dependencies installed. |
| `.\.venv\Scripts\python.exe -m app.rag.embeddings` with offline flags | Exit 0: pinned model/revision, `dimensions: 384`, `local_only: true`. |
| `.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit -q -p no:cacheprovider` with offline flags | Exit 0: `39 passed, 1 warning in 28.91s`. |
| `docker compose up -d --wait db db_test` | Exit 0; both healthy on 5432/5433. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `182 passed, 1 warning in 91.96s`; no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `50 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0. |

The first full attempt failed collection because the unit/integration test modules
shared a filename; pytest now uses importlib collection. An initial sandboxed unit
run had two Windows temporary-directory permission errors; the approved retry
passed all 39 tests. The final full run had no failures, errors or skips.
The remaining pytest warning is the existing Starlette/httpx deprecation. A
tokenizer diagnostic during the deliberate oversized-input rejection test is
expected: that input is rejected before model inference, never truncated.

Live output confirmed six normalized `vector(384)` seed chunks with unchanged
IDs/timestamps on repeat indexing, exact model/migration agreement, and successful
head/base/head migrations. The tests use no cloud LLM adapter or provider key.
The recorder captures the actual context serialization intended for a future
adapter; no claim is made that an arbitrary LLM will always follow safe behavior.
No planner, generic agent, booking tools, streaming or UI was implemented.

Container verification also completed:

| Command | Observed result |
| --- | --- |
| `docker compose build api` | Exit 0; CPU embedding dependencies and the pinned model cached in the image. |
| `docker run --rm --network none --mount "type=bind,source=$((Get-Location).Path)\backend\app,target=/app/app,readonly" ai-poweredhrassistant-api python -m app.rag.embeddings` | Exit 0 under the non-root image user: current workspace code used the image cache and returned `dimensions: 384`, `local_only: true`, with networking disabled. |

This run did not deploy the API or apply Phase 4 migrations/indexes to persistent
development/test databases. Build with `--build` when starting the final source
in a container; the offline container check mounted the final workspace code
read-only over the image's cached runtime/model. First-time dependency/model
downloads were slow, but subsequent runtime and verification use local assets.

## Phase 5: self-only HR tools and leave validation

The typed tools `get_leave_balance`, `get_employee_profile`, `get_leave_history`
and `validate_leave_request` use authorized SQL reads. They do not use policy
embeddings for mutable numeric facts. The server actor controls company/user;
another subject is forbidden even for HR. Maya's balance is 12 and Ravi's 5.
Leila has no seeded balance and receives `not_found`, not an invented zero.

Authenticated routes:

| Method/path | Behavior |
| --- | --- |
| `GET /api/v1/leave/balance` | Existing `{days_left, as_of}` contract preserved; Decimal days encoded as a string. |
| `GET /api/v1/employee/profile` | Safe own display name, department and start date; 404 if absent. Profiles are not part of the current seed. |
| `GET /api/v1/leave/history?limit=20&cursor=...` | `{items,next_cursor}`, newest first with stable timestamp/UUID pagination; limits 1-100. Seed history is empty. |
| `POST /api/v1/leave/validate` | Advisory validation only; existing exact Origin and `X-CSRF-Token` checks apply. |

Validation input:

```json
{"start_date":"2026-11-09","end_date":"2026-11-11","leave_type":"annual"}
```

Dates must be `YYYY-MM-DD`. Annual leave is the only supported type; unknown
authority fields, timestamps and unsupported types return 422. A well-formed
range returns `valid`, Decimal `days`/`available_days`, `overlaps_existing`,
typed `errors` and an explicit fictional-convention label. Business reasons are
`date_order`, `range_too_long`, `no_workdays`, `overlap`, `insufficient_balance`.
For example, Maya's range above validates as 3 days with 12 available; Ravi's
November 9-16 range is 6 weekdays and returns `insufficient_balance`.

**FICTIONAL DEMONSTRATION CONVENTION:** count Monday-Friday inclusively, without
verified employer weekends, public holidays, accrual or half-days. Cap one range
at 366 calendar days. No future-date policy is inferred. Inclusive overlaps with
own booked/pending leave requests block validation; cancelled or other people's
requests do not. This is not an actual Summit/Pebble entitlement or approval.

Missing self balance/profile yields 404, another tool subject yields 403, and
malformed pagination yields 422. Cursors are untrusted positions and cannot widen
self scope. No HTTP route accepts company/role/user authority selectors.

Validation saves nothing: no proposals, bookings, balance changes, reservations,
history or audit writes. Concurrent booking safety and human confirmation remain
Phase 7 work; any future confirmation must revalidate in its own transaction.
No new dependencies, migrations or seed data were required. The existing full
disposable-database runner also runs the Phase 5 tests:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

Observed Phase 5 results on 2026-11-08:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `242 passed, 1 warning in 121.90s`; no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `58 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0. |

The one warning remains the existing Starlette/httpx deprecation. The full run
also retained the existing Phase 4 oversized-input rejection diagnostic and
passed real embedding/pgvector regressions and migration head/base/head checks.
New Phase 5 tests cover 12/5 SQL balances, self-only profile/history, HR denial
of other subjects, cursor ties and invalid cursors, weekday/date boundaries,
insufficient balance, own overlap status rules, HTTP spoofing/CSRF, and full-row
snapshots across all 15 application tables. Captured HR tool SQL was SELECT-only.
Only rolled-back test fixtures created bookings/history to exercise overlap;
no application booking/proposal endpoint or write service was added. Persistent
dev/test data was unchanged. No later phase was started.

## Phase 6: typed planning and parallel authorized reads

`app/agent/` contains typed plan/state models, an LLM protocol, deterministic
`FakeLLM`, a closed read-tool registry and a dependency-aware executor. The fake
adapter recognizes a small documented demo vocabulary; it is not a live provider
or a general natural-language understanding implementation. No dependencies,
schema migrations or seed changes were required.

A single message can produce balance, policy, profile, history and dated-leave
validation branches. Ready independent reads run concurrently on separate SQL
connections; every branch rechecks the server actor and uses existing scoped
tools. HR reads use READ ONLY transactions. Policy reads retain ordinary
transactions for their shared permission-check locks; no HR mutations are called.
Validation waits for balance. Missing dates produce clarification rather than
invented dates or a booked leave. Cycles, missing dependencies, unknown tools and
actor/company/SQL arguments in plans are rejected before dispatch.

Each result preserves the original request verbatim, the validated plan, ordered
subtask data, tool status transitions, sanitized failures and a combined answer.
An independent branch failure does not erase completed results. Failed
dependencies skip downstream work; composition failure retains prior results.
The FakeLLM combines balances, actual cited assignment attendance sentences,
policy references, validation conventions and clarifications. Other policy
subjects remain structured authorized evidence; no free-form live LLM answer is
claimed. Retrieved directives are not replanned or dispatched as tool calls.

Actor activity/role and source access/version/hash are checked again before
composition. Revoked source content is filtered out; actor revocation prevents
composition and clears result payloads. Task replay rechecks source access and
clears the rendered answer if access changed. Model prompts do not establish
permissions. The transcript is owner/company scoped.

Authenticated endpoints (existing Origin/CSRF checks apply to POSTs):

| Method/path | Phase 6 behavior |
| --- | --- |
| `POST /api/v1/conversations` | Accept `{title?}`, create own conversation, return 201. |
| `GET /api/v1/conversations/{id}` | Own conversation and task summaries only; 404 for inaccessible IDs. |
| `POST /api/v1/conversations/{id}/tasks` | Accept `{message}`, run in foreground and return HTTP 200 with the finished execution state. A second active task in that conversation gets 409. |
| `GET /api/v1/tasks/{id}` | Own persisted original request, status and execution snapshot. |

Example task body:

```json
{"message":"Tell me my remaining leaves, explain the late attendance policy, and prepare a leave request for three days."}
```

For Maya this executes SQL balance + real policy retrieval, retains 12 days and
Summit's one-day pay-cut evidence, and asks for start/end dates. Task `status`
is completed/failed; `outcome` separately records completed, partial,
needs_clarification or refused. A clarification outcome has no proposal and is
not awaiting confirmation. With explicit ISO dates, validation follows balance
and still writes no booking or balance change.

Minimal persistence writes only conversation/message/task metadata, including
execution snapshots in `Task.plan`. No task notes/events, action proposals,
bookings, balances, leave history or audit writes are added. The endpoint does
not claim background execution: HTTP 202 queueing, durable leases/recovery,
mid-run editing, cancellation, event replay, streaming and UI are deferred.
A process interruption can leave a running task requiring operator resolution
until Phase 8. No `/tasks/{id}/instructions` endpoint exists in this phase.

Run all tests with the existing disposable-database harness:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
.\.venv\Scripts\python.exe -m pip check
```

Tests include real simultaneous PostgreSQL connections held at a barrier with
distinct backend PIDs; deterministic plan/DAG checks; original-request and trace
persistence; triple intent; dependency skips; partial/composition failures;
poison isolation; actor/source revocation; ownership/spoofing; and unchanged HR
business rows. Parallel-connection tests commit fixtures only inside the guarded
disposable database and clean them up there. Persistent dev/test data is unchanged.

Observed Phase 6 results on 2026-11-08:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/test_planner.py -q -p no:cacheprovider` | Exit 0: `11 passed in 0.33s`. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Final exit 0: `268 passed, 1 warning in 197.02s`; no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `68 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0. |

The initial full run had 5 failures because the final policy authorization
recheck needed `source_sha256`, which the direct policy repository projection
did not include. The projection was corrected; those tasks failed closed rather
than forwarding unverified results. The corrected run passed 268 tests, followed
by the final run above with the combined attendance-answer assertion included.
The remaining warning is the existing Starlette/httpx deprecation; the deliberate
Phase 4 over-limit-token test still emits its expected tokenizer diagnostic.

Tests exercised real embeddings/pgvector as before, genuine concurrent database
connections, no HR writes, scoped task persistence, API ownership, refusal and
clarification, actor/source revocation and retained partial results. No API
deployment, new dependency installation, migration or persistent dev/test data
change was performed in this phase. Phase 7 remains unimplemented.

## Phase 7: proposals and human-confirmed booking

Proposal writes are isolated in `app/services/proposals.py`; the existing HR
validation tools and LLM registry remain read-only. No confirmation/cancellation
tool is exposed to the model. Creation is an explicit client action, not an
autonomous planner step. No new dependency, migration or seed change was needed.

All endpoints below are authenticated and owner/company scoped. POSTs require
the existing exact Origin and `X-CSRF-Token`. HR cannot act on another person's
proposal, even in the same company. Other/inaccessible IDs return 404.

| Method/path | Body and result |
| --- | --- |
| `POST /api/v1/leave/proposals` | `{task_id,start_date,end_date,leave_type?}` referencing your completed task. Returns 201 with ID, pending status, version, dates, server-calculated days, expiry and fictional calendar identity. |
| `GET /api/v1/leave/proposals/{id}` | Review your proposal and its current state/version. |
| `POST /api/v1/leave/proposals/{id}/confirm` | `{expected_version:1}`; success returns booked request ID, remaining balance and new proposal version. |
| `POST /api/v1/leave/proposals/{id}/cancel` | `{expected_version:1}`; cancels only an owned pending proposal, without booking, debit or refund. |

Use the proposal ID/version returned by creation. The server assigns a 15-minute
lifetime; callers cannot provide identity, days, expiry or approval fields.
Versions must be positive JSON integers (not strings or booleans). Repeating the
same pending creation returns the same ID; a different active payload for that
task gets 409. Pending proposals reserve no days. A GET does not update expiry;
an expired action commits `expired`/version+1 and returns 409.

Before confirmation, Maya's balance stays 12 and no leave request/history is
created. Confirming November 9-11 books exactly one 3-day request and changes
the balance to 9 under the **fictional inclusive Monday-Friday convention**.
There is no verified holiday calendar, manager-approval stage or real entitlement
inference. Duplicate, cancelled, expired or stale confirmations return 409.

Confirmation uses a fresh transaction that rechecks the authenticated actor,
locks the owned proposal and own balance with FOR UPDATE, checks database time
after lock waits, revalidates dates/day amount/balance/overlap, then atomically
writes the booking, debit/version, proposal transition, leave history and audit.
The unique proposal-to-booking constraint prevents duplicate effects. Different
proposals serialize on the same balance row and recheck after earlier commits.
The transaction commits before the successful HTTP response is sent. Unexpected
write errors roll back all effects; cancellation does not reverse booked leave.

The existing task planner still does not call mutation services. Its balance,
policy and validation results remain advisory until the authenticated client
explicitly creates and confirms a proposal. No mid-run editing, durable worker,
streaming or UI was added. Persistent dev/test data remains unchanged.

Observed Phase 7 verification on 2026-11-08:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/test_proposals.py -q -p no:cacheprovider` | Exit 0: `6 passed in 0.05s`. |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `297 passed, 1 warning in 148.30s`; no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `73 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0. |

The warning remains the existing Starlette/httpx deprecation; the previous
oversized-token rejection diagnostic is expected. New real-DB cases verify
duplicate and competing-proposal races, confirm/cancel races, stale/expiry
transitions, expiry after balance-lock waiting, rollback after a final write
failure, payload mismatch, cross-tenant/same-company-HR denial, CSRF/Origin and
model tool rejection. Booking test databases are dropped without deleting or
disabling append-only history/audit records. No API deployment or later phase
was performed.


## Phase 8: durable tasks and mid-run instructions

Task creation now returns **202** with `{task_id,status,revision}`. Poll
`GET /api/v1/tasks/{task_id}` for the persisted execution, trace, original request,
append-only instructions and `instruction_revision`. The owner/company and
Origin/CSRF rules continue to apply.

- `POST /api/v1/tasks/{task_id}/instructions` accepts `{message,expected_revision?,client_note_id?}`.
  It returns 202 with the same task ID and new revision. Stale revisions or
  conflicting replay keys return 409. Replaying an identical note key returns
  its original revision without appending again. New notes on terminal tasks
  return 409; inaccessible tasks return 404.
- `POST /api/v1/tasks/{task_id}/cancel` enters `cancelling` and returns 202.
  The worker then persists `cancelled`. Terminal tasks return 409.
- Instructions and cancellation invalidate pending proposals, without reversing
  confirmed leave. The LLM still cannot confirm or book anything.

The lifespan starts a two-worker PostgreSQL-backed runner. Leases use fresh
claim tokens, database time and fenced saves; restart recovery waits for the
30-second lease expiry. Completed reads are checkpointed and reused. An
interrupted read without a completed checkpoint may retry. Final task state and
one deterministic assistant message commit together. Public snapshots omit the
internal cache and recheck policy access.

The original request remains exact and database-immutable. New goals and date
changes replan at checkpoints under the same ID; plain/formal/brief notes revise
the deterministic FakeLLM output. This is a bounded demo adapter, with eight
steps and 64 notes, rather than general instruction interpretation. Set
`TASK_RUNNER_ENABLED=false` only when deliberately disabling local workers.
Apply the new migration before starting the API:

```powershell
docker compose run --rm api alembic upgrade head
.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_midrun.py
.\.venv\Scripts\python.exe scripts/verify_phase2.py
```

The verification script now accepts optional pytest paths while retaining
configurable `--dev-port` and `--test-port`. All DB tests run in disposable test
DBs; verification does not migrate or seed persistent dev/test databases.
See [the Phase 8 decision](docs/adr/0009-durable-tasks-and-instructions.md).
No streaming, task events or UI was added.


Observed Phase 8 verification on 2026-11-08:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | Exit 0: `308 passed, 1 warning in 156.96s`; no skips. Empty DB upgrade, schema/model match and head/base/head round trip passed. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `79 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0; repository implementation files remain untracked. |

The existing Starlette/httpx deprecation warning and intentional oversized-token
rejection diagnostic remain. During development, the focused test command first
rejected positional paths (the verification script now supports them), then four
tests failed at fixture setup due to an SQLAlchemy driver URL passed to Settings.
The fixture URL was corrected; the full passing run above includes all six new
real-DB mid-run tests and five note-merging unit tests. No dependency installation,
deployment or migration of persistent databases was performed.

Final verification after the error-path review:
`.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_midrun.py backend/tests/unit`
exited 0 with `91 passed, 1 warning in 36.56s`. Lint, formatting and dependency
checks were also repeated successfully.


## Phase 9: persisted events and SSE

`POST /api/v1/conversations/{id}/tasks` also returns `events_url`. Subscribe to
that URL with the existing authenticated cookie:

```http
GET /api/v1/tasks/{task_id}/events
Accept: text/event-stream
Last-Event-ID: 12
```

The optional `?after=12` cursor is supported; `Last-Event-ID` wins when both are
present. Cursors must be nonnegative decimal integers within PostgreSQL bigint
range and cannot be ahead of that task's log (422). Missing authentication gets
401; other people's tasks get 404, including same-company HR. No identity or
role query parameters are accepted.

Data frames carry monotonic per-task IDs and JSON envelopes:

```text
id: 13
event: tool.status
data: {"task_id":"...","seq":13,"revision":0,"payload":{"subtask_id":"balance","tool":"get_leave_balance","status":"completed","error":null}}

```

Event types are `task.status`, `task.updated`, `tool.status`, `assistant.delta`,
`proposal.updated` and `task.terminal`. A terminal payload explicitly identifies
`completed`, `failed` or `cancelled`. Replay emits only IDs greater than the
cursor; clients should retain the latest ID and apply each data event once.
Multiple subscribers receive the same log independently. Heartbeat comments
arrive every 15 seconds without consuming IDs. Disconnecting does not cancel a
task. Logout, session expiry and revoked ownership/access close the stream.

After draining a terminal task's log the connection closes. Reconnecting at its
latest ID returns 204. Explicit human proposal changes may append additional
proposal events after the execution terminal; reconnecting retrieves them.
Streaming does not create or confirm a proposal. No frontend was added.

The API polls in short transactions, sends `Cache-Control: no-store` and
`X-Accel-Buffering: no`, and rechecks policy provenance before replaying saved
answer fragments. Revoked fragments are redacted while retaining their IDs.
Current FakeLLM returns a full answer: assistant deltas are durable chunks of
that finished answer, while tool/note events arrive during execution.

Apply migration `0005_event_baselines` before starting the updated API. It adds
one baseline event for each older task that has no log; it does not invent
historical answer/tool events. Persistent dev/test DBs are not changed by tests.

```powershell
docker compose run --rm api alembic upgrade head
.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_sse.py
.\.venv\Scripts\python.exe scripts/verify_phase2.py
```

See [the Phase 9 decision](docs/adr/0010-persisted-task-events-and-sse.md).


Phase 9 verification on 2026-11-09:

| Command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_sse.py backend/tests/unit/test_events.py` | Exit 0: `23 passed in 27.92s`. Real HTTP/Uvicorn, disposable PostgreSQL DBs, no skips. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0: `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0: `85 files already formatted`. |
| `.\.venv\Scripts\python.exe -m pip check` | Exit 0: `No broken requirements found.` |
| `git diff --check` | Exit 0; implementation files remain untracked. |

The first full regression run reported `1 failed, 329 passed, 1 warning in
216.13s`: the multi-batch replay test treated a valid heartbeat comment as a data
frame and tried to read its ID. Its assertion now checks IDs on data frames;
heartbeat comments correctly have none. The passing focused run above includes
the correction plus proposal-event replay after execution, duplicate human
confirmation handling and all new event serializer tests. The focused SSE and
proposal regression run also passed `31 passed, 1 warning in 58.36s`.


Final full regression:
`.\.venv\Scripts\python.exe scripts/verify_phase2.py` exited 0 with
**`331 passed, 1 warning in 181.41s`**, no skips. Empty-DB migration/model checks,
head/base/head migration round trip, real pgvector/embeddings and all previous
phase tests passed. The warning is the existing Starlette/httpx deprecation;
the deliberate oversized-token rejection test emits its expected diagnostic.
No dependencies were installed, no frontend was built, and no persistent DB
migration, deployment or later phase was performed.


## Phase 10: React workspace

`frontend/` contains the React/Vite/TypeScript UI: credential login, server-derived
company/role header, current-session conversation sidebar, chat, live tool
activity, source excerpts, reconnect state and explicit approval cards. The
composer remains editable during execution; sending posts an instruction to the
existing task. A new task is created only when the selected request is terminal.

Preparing a leave proposal is an explicit action. Its server-calculated days,
expiry and **fictional inclusive-weekday convention** are shown before a separate
**Confirm booking** button. No effect hook or streamed response confirms leave.
Permission and conflict errors stay visible without exposing server internals.

Use Node 22.14 or newer compatible Node 22 releases. From `frontend/`:

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run dev
```

On non-Windows systems use `npm` instead of `npm.cmd`. Start the existing API
separately with `APP_ORIGIN=http://127.0.0.1:5173` and
`SESSION_COOKIE_SECURE=false` for this local HTTP demo. Open exactly
`http://127.0.0.1:5173`. Vite proxies `/api` to `http://127.0.0.1:8000`; override
`API_PROXY_TARGET` in its environment when the API uses a different host port.
The browser never contacts a separate API origin, and existing CSRF checks stay
in place. Use HTTPS and secure cookies for hosted environments.

For Docker, set `APP_ORIGIN=http://localhost:5173` in `.env` (or the exact browser
origin matching your `FRONTEND_PORT`), then use:

```powershell
docker compose --profile ui up --build -d
```

The optional frontend service serves the build through Nginx on
`${FRONTEND_PORT:-5173}`, proxying to the API with buffering disabled for SSE.
Apply the already-required backend migrations and seed/index commands before
using the UI; this phase does not migrate or reseed persistent databases.

Sidebar history and login display state are in memory because the current API
has no session-inspection or conversation-list endpoint. Refresh requires a new
sign-in; server-side tasks remain persisted. The UI replays task events without
duplicating text and discards stale-generation deltas. Backend assistant deltas
are still chunks of a completed FakeLLM response, rather than live model tokens.

Run the real-browser smoke from the repository root after `npm ci`:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_frontend.py
```

It launches temporary Vite/API servers and a disposable PostgreSQL DB. Windows
uses installed Edge; elsewhere install Playwright Chromium first with
`npx playwright install chromium` in `frontend`. Screenshots are saved under
ignored `frontend/test-results/`. The smoke verifies the same task ID during a
paused-LLM note, one human-confirmed booking, tenant-switch clearing, permission
feedback and desktop/mobile layouts. Its inspection/release endpoints are
attached only to the ephemeral test app, never the production API.

See [the Phase 10 decision](docs/adr/0011-react-workspace.md). No Phase 11 audit,
production deployment or later-phase work was performed.


Observed Phase 10 verification on 2026-11-09:

| Command | Result |
| --- | --- |
| `npm.cmd ci` (frontend) | Exit 0; 27 packages installed, 0 vulnerabilities. |
| `npm.cmd run typecheck` (frontend) | Exit 0; no TypeScript errors. |
| `npm.cmd test` (frontend) | Exit 0; 6 tests passed, 0 failed, 0 skipped. Node 22.14 emits its experimental type-stripping warning. |
| `npm.cmd run build` (frontend) | Exit 0; Vite 7.3.7, 32 modules, built in 891ms. JS 239.36 kB (75.20 kB gzip); CSS 9.65 kB (2.94 kB gzip). |
| `.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_frontend.py backend/tests/integration/test_sse.py` | Exit 0; `13 passed in 41.40s`, no skips. Real headless Edge + Vite proxy + API SSE + disposable PostgreSQL. |
| `npm.cmd exec -- prettier --check src tests vite.config.ts package.json tsconfig.json` | Exit 0; all files formatted. |
| `.\.venv\Scripts\python.exe -m ruff check backend scripts` | Exit 0; all checks passed. |
| `.\.venv\Scripts\python.exe -m ruff format --check backend scripts` | Exit 0; 86 files already formatted. |
| `docker compose --profile ui config -q` | Exit 0. Docker image build/start was not performed. |
| `git diff --check` | Exit 0; implementation files remain untracked. |

The smoke asserts one append-only note under the original task ID while FakeLLM
is paused, no booking/balance change before confirmation, and exactly one booked
request with a 12-to-9 balance change afterward. It checks permission feedback,
tenant switching and mobile layouts, including the approval card. Desktop and
mobile screenshots were visually inspected. All test DBs/processes are cleaned
up; persistent dev/test data and the local `.env` remain unchanged.

Earlier validation caught two JSX syntax errors and two smoke-harness issues
(an overly exact text selector and a missing browser request base URL); these
were corrected before the passing final run. The initial dependency tree's test
runner reported vulnerabilities, so it was replaced with Node's built-in runner;
the clean final install audited zero vulnerabilities. No later phase or deployment
was performed.


## Phase 11: acceptance matrix and adversarial verification

See [the Phase 11 verification report](docs/phase11_verification.md) for T01-T30
mappings, reproduced failures, exact command output and known limitations.
Scoped fixes keep the queue alive through DB outages, fail promptly on missing
model assets, and redact sensitive query/client metadata in packaged access logs.
New tests cover real connection failure, missing assets, SQL-looking input,
retrieved booking directives and access-log privacy. Existing assertions and
real vector/embedding requirements remain intact.

Final full run: **338 passed, 1 warning in 290.51s**, no skips. Frontend: **6 tests
passed**, typecheck/build passed, clean install audited **0 vulnerabilities**.
An isolated Docker build/start/index/restart/DB-outage audit passed, including
same-task/SSE persistence and body/query secret-canary checks. Its containers and
volumes were removed; persistent dev/test data was not migrated or seeded.

```bash
bash scripts/verify_demo.sh --docker
```

PowerShell may run the two Python drivers directly:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
.\.venv\Scripts\python.exe scripts/verify_phase11_docker.py
```

Local Uvicorn launches should add `--log-config backend/logging.json` alongside
`--app-dir backend`; Docker already uses the packaged redacted configuration.
The default unconfigured Uvicorn access logger includes query strings. Cold
synchronous policy search exceeded a 20-second client timeout during audit;
the normal asynchronous task workflow handles real model initialization.
FakeLLM, completed-answer delta chunks, in-memory sessions and the fictional
weekday-only leave calendar remain explicit demo limits. Phase 12 is not done.
