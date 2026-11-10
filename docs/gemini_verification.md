# Gemini default and dual-provider verification

Default: `LLM_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.6-flash`.
Optional: `LLM_PROVIDER=openai` + existing OpenAI model/key settings.
Offline/manual: `LLM_PROVIDER=fake`. Providers never silently fall back.

The official Google Gen AI SDK 2.34.0 and existing OpenAI SDK 2.54.0 were tested.
Shared typed plans/context/prompts were extracted into `agent/live_llm.py`;
`agent/gemini_llm.py` adds Google's async native JSON Schema implementation.
Provider selection, server settings, runtime metadata, frontend provider type and
error display, Compose, `.env.example`, local `.env`, live smoke and offline
test guards/drivers were updated. Gemini is default in Compose/local dotenv;
direct host settings still default to fake unless explicitly configured.

Credentials remain server-only. The local `.env` provider changed to Gemini,
`GEMINI_MODEL` and `GEMINI_API_KEY` entries were added; the user supplied the key
locally. Existing database/authentication/OpenAI credentials were preserved.
No schema/migration, seed, database-role/password or volume changes were needed.
No booking or balance change was part of verification.

## Executed checks

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
# 391 passed, 1 warning in 324.61s (0:05:24)
```

The full suite included the real API/Vite/Edge smoke, real local vector SQL,
poisoned-context isolation, owner-only/revoked-source history, approval races and
exactly-once confirmation. The sole warning is the existing Starlette/httpx
TestClient deprecation. A tokenizer boundary diagnostic is also logged by its
passing length-budget test. No external LLM calls occur in this suite.

```powershell
.\.venv\Scripts\python.exe scripts/verify_live_llm.py
```

Actual Google API success, not a mock:

```json
{"provider":"gemini","model":"gemini-3.6-flash","usage":{"calls":2,"input_tokens":566,"output_tokens":111},"sdk_smoke":"passed"}
```

This verifies a real typed greeting plan and composed answer without HR records.
It does not establish a real-provider authenticated browser/HR end-to-end test.
An initial native Google `response_schema` request failed because its translated
`additional_properties` field was unsupported. The implementation now sends
standard `response_json_schema`, keeps strict local validation and passes the
real API check. A separate diagnostic greeting also encountered a 504 with a
15-second diagnostic deadline; subsequent configured plan/answer calls succeeded.

The API and frontend were subsequently rebuilt and restarted using the existing
Compose stack. API health passed, UI HTTP was 200, and `/api/v1/health/live`
through the UI proxy was 200. The existing PostgreSQL containers were retained.

A live check **inside the deployed API container** loaded the demo actor's scope
from SQL and executed the existing executor with no persistence callback:

```json
{"live_server_read":"passed","provider":"gemini","model":"gemini-3.6-flash","tool_statuses":[["get_leave_balance","completed"]],"booking_workflow":false,"usage":{"calls":2,"input_tokens":649,"output_tokens":217},"persisted_task":false,"error":null}
```

This verifies Gemini planning, an authorized real SQL balance read, and live
answer composition with no booking workflow. It created no task/proposal/booking
records and did not deduct balance. No balance value, credentials or answer text
was printed. This is a server-side check, not an authenticated Google-backed
browser test; the automated browser matrix separately uses FakeLLM.

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/test_gemini_provider.py backend/tests/unit/test_openai_provider.py -q -p no:cacheprovider
# 27 passed in 14.03s
.\.venv\Scripts\python.exe -m ruff check --no-cache backend scripts
# All checks passed!
.\.venv\Scripts\python.exe -m ruff format --check --no-cache backend scripts
# 105 files already formatted
.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
git -c core.safecrlf=false diff --check
# exit 0
cd frontend
npm.cmd run typecheck
npm.cmd test
# 11 passed; 0 failed
npm.cmd run build
# built successfully; 33 modules transformed
cd ..
```

Provider mocks exercise official SDK HTTP serialization, schema/usage, bounded
retry, timeout, malformed/truncated/mutation plans, sanitized errors and missing
Gemini key despite an available OpenAI key. Both keys and Google's alternate key
environment variable are stripped in offline tests; Google/OpenAI HTTP egress is
blocked outside mock transports. Real local MiniLM (384 dimensions), pgvector,
tenant/role/self restrictions, workflow checks, append-only instructions, replay
and transactional human confirmation remain shared.

## Run and switch

Edit the ignored `.env` with your editor:

```dotenv
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.6-flash
GEMINI_API_KEY=<your locally saved Google AI Studio key>
```

```powershell
docker compose --profile ui up -d --build --wait api frontend
```

Sign in at http://localhost:5173 with the existing demo credentials. A restart
requires login again. The provider badge should show `gemini / gemini-3.6-flash`;
successful task metadata records actual provider/model/usage. For OpenAI, change
`LLM_PROVIDER=openai` and configure its key/model, then run the same command. For
fake, set `LLM_PROVIDER=fake`. Do not reset/reseed existing data to change LLMs.

Google access, rate and billing quotas are account/project dependent. A provider
key does not guarantee unlimited free quota. Live claims here are limited to
the successful calls explicitly recorded; automated browser/security tests use
FakeLLM and real SQL/vectors.

## Updated salary fixture (2026-11-10)

The CEO source now contains supplementary fictional salary figures. Its manifest
title/provenance and visible Markdown status were corrected to explicitly mark
fictional demonstration data. Leila-only access is retained. The seed regression
now checks fictional labeling and exact source-body persistence rather than the
obsolete requirement that this supplementary document contain no digits. User
changes to fictional figures therefore do not require a hardcoded test amount.
Original company/user/balance/attendance facts, password hashing, seed no-op
repeatability, source hashes and access assertions remain checked.

Focused seed, real-vector and policy-permission verification: **36 passed,
1 existing warning in 34.70s**. Final seed-only verification: **7 passed in 5.98s**.
These commands use disposable databases and do not refresh the running demo DB.
Full verification after the salary fixture update:
`python scripts/verify_phase2.py` — **391 passed, 1 warning in 277.76s (0:04:37)**.
The warning remains the existing Starlette/httpx TestClient deprecation.
