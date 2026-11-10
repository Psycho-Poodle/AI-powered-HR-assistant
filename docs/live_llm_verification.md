# Live provider and workflow verification

Historical OpenAI integration results are below. The current default and latest
Gemini evidence are in [Gemini verification](gemini_verification.md) and
[ADR 0013](adr/0013-gemini-provider.md).

Implementation uses the official OpenAI Python SDK (verified locally with 2.54.0),
asynchronous Responses structured planning and answer composition. Default Docker
model is exactly `gpt-5.4-mini`; `LLM_PROVIDER=fake` remains explicit offline mode.
No external OpenAI request was made during automated tests. No API key is
configured locally, so **real-provider/browser end-to-end smoke was not executed**.
Mocked SDK success does not establish account/model/network availability.

Follow-up live diagnostic: after a key was configured, one minimal Responses
request from the running API container returned HTTP 429 with
`code=credit_balance_exhausted`, `type=insufficient_quota`. No HR data was sent;
only allowlisted error identifiers were printed. This is an unsuccessful live
attempt, not a successful provider/browser end-to-end verification. The adapter
now distinguishes quota/billing errors (`provider_quota_exhausted`) from temporary
rate limits; the UI directs administrators to API billing/limits instead of
suggesting that waiting alone will resolve exhausted credit.
Follow-up verification: provider tests **14 passed in 5.29s**; frontend tests
**11 passed**; typecheck/build and Ruff passed. These changes have not recreated
the currently running demo containers.

## Commands and results

From the repository root, Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/verify_phase2.py
# 373 passed, 1 warning in 351.04s (0:05:51)

.\.venv\Scripts\python.exe scripts/verify_phase2.py backend/tests/integration/test_llm_history.py
# 1 passed in 34.55s

.\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/unit/test_replanning.py backend/tests/unit/test_planner.py backend/tests/unit/test_openai_provider.py backend/tests/unit/test_workflow_intents.py -q -p no:cacheprovider
# 46 passed in 10.21s (after final target-check review)

.\.venv\Scripts\python.exe -m ruff check backend scripts
# All checks passed!
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
# 102 files already formatted (final --no-cache check)
.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
git -c core.safecrlf=false diff --check
# exit 0, no whitespace errors
docker compose --profile ui config -q
# exit 0; no configuration or credentials printed

cd frontend
npm.cmd run typecheck
# exit 0
npm.cmd test
# tests 11; pass 11; fail 0
npm.cmd run build
# 33 modules transformed; built successfully
npm.cmd exec -- prettier --check src tests package.json
# All matched files use Prettier code style!
npm.cmd audit --audit-level=high
# found 0 vulnerabilities
cd ..

.\.venv\Scripts\python.exe scripts/verify_phase11_docker.py
# Docker: api + frontend images built
# Docker: clean isolated startup, migrations, seed and real local index passed
# Docker: UI proxy, keyless policy SQL, restart/SSE persistence and real DB-outage recovery passed
# Docker: logs contain no tested password/session-secret/request canaries
# {"result": "passed", "persistent_dev_data": "untouched"} (project field omitted)
```

The test drivers use uniquely named disposable databases/stacks, explicit fake
selection and offline pinned MiniLM assets. Persistent development databases,
roles/passwords, `.env`, application migrations and volumes were not changed.
The Docker verifier cleans up only its own temporary project. The current running
development containers were not switched to live mode.

The full matrix includes genuine pgvector queries, seed repeatability, tenant
foreign keys, self/role/tenant scope, poisoned-context isolation, notes/revisions,
leases/recovery, transactional races and exactly-once human confirmation, SSE
replay/subscribers and the real API/Vite/Edge browser smoke. New checks cover
structured SDK handling, sanitized timeout/provider failures, missing credentials,
read-only form suppression, explicit initiation/continuation, resolved workflows,
task/conversation switches, preserved drafts and replay after confirmation.
The additional real DB history test excludes another owner and suppresses a
previous answer after its supporting sources become unavailable.
That test and the final live-note target-refusal regression were added after the
full run collected its tests; their passing focused commands are recorded above.
The sole pytest warning is the existing Starlette/httpx TestClient deprecation.
The token-budget boundary test also logs a tokenizer length diagnostic; it passes.

Earlier validation exposed two outdated transaction fixtures without initiated
workflows and browser submission/cold-index setup issues. Fixtures now establish
explicit leave intent; browser tests wait for the submitted task and index real
policies before starting, matching README setup. Race/balance/security assertions
were retained; policy-answer and navigation assertions were added. No tests were
disabled or replaced with mock vectors. The npm audit initially encountered
sandbox registry/cache restrictions; the authorized retry reported zero findings.

## Changed areas and limits

- Backend: `agent/openai_llm.py`, `providers.py`, `errors.py`, `workflows.py`, typed
  plan/execution state, existing planner/executor/runner, configuration/lifespan,
  `schemas/workflow.py`, `services/task_context.py`, proposal prerequisite,
  authenticated runtime/task snapshots and typed workflow SSE events.
- Frontend: API types, task reducer/stream refresh, App snapshot/error/provider
  handling, `components/LeaveRequestForm.tsx`, per-task drafts, badge styling,
  component/replay/browser tests, package manifest/lock (tsx test loader).
- Environment/verification: `.env.example`, Compose provider settings, backend
  dependency manifest, offline test guards/drivers/fixtures/regressions,
  `scripts/verify_live_llm.py`, README and ADR 0012.

No new database schema or autonomous writes. Existing human confirmation remains
the only booking path. English initiation evidence is deliberately conservative;
unsupported phrasing should clarify. The most recent four owned turns are
bounded context, not unlimited memory. SDK usage records successful reported
tokens and logical calls, not a billing ledger or unknown retry consumption.
Tools stream progress; answer chunks follow completed composition. Sidebar and
unsubmitted drafts remain session memory; a full browser reload clears them.
Production SSO/session storage, rate limiting and deployment remain out of scope.

## Start the real demo

Configure the ignored local `.env` using your editor:

```dotenv
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5.4-mini
OPENAI_API_KEY=<your local key>
```

For the existing seeded installation:

```powershell
docker compose --profile ui config -q
docker compose --profile ui up -d --build --wait
```

Open http://localhost:5173 and use the existing seeded username/password. Fresh
install commands, seed accounts and provider troubleshooting are in README.
Check the provider badge, then a successfully completed task's authenticated
`plan.execution.provider`, `model` and nonzero successful token usage. To choose
keyless manual mode, set `LLM_PROVIDER=fake` and recreate the API container.
The optional paid SDK-only smoke is `python scripts/verify_live_llm.py`; it is
separate from browser verification and never invoked by offline tests.
