# Phase 11 — integration and adversarial verification

Verification date: 2026-11-09. Scope: execute the acceptance matrix, close specific
coverage gaps, fix reproduced failures, verify isolated Docker startup/restart,
and report limits. No Phase 12 rewrite or production deployment.

## Matrix evidence

All tests below use the existing authorized repositories/API. Integration tests
run in disposable migrated PostgreSQL databases; embeddings and vector SQL are
real. Only deterministic LLM adapters and test transport/failure controls are
substituted. Names refer to files under `backend/tests`.

| ID | Automated evidence |
| --- | --- |
| T01 | `security/test_poison.py::test_poison_cannot_widen_context_authority` and `security/test_isolation.py::test_policy_permission_matrix`: Summit actors receive no Pebble source content. |
| T02 | The same parameterized poison/isolation tests for Ravi enforce the reverse boundary. |
| T03 | `security/test_poison.py::test_leila_can_retrieve_salary_but_never_pebble` and `integration/test_multitask.py::test_foreign_requests_and_forged_read_target_cannot_widen_actor`. |
| T04 | Poison tests capture the actual reference-context payload: Maya lacks the salary canary; Leila receives it; another HR identity does not inherit the specific-user ACL. |
| T05 | `integration/test_multitask.py::test_poison_data_cannot_dispatch_writes_or_leak_other_tenant`: poison is actually present in model input, the canonical attendance answer remains correct and business rows do not change. |
| T06 | `security/test_isolation.py::test_self_balance_from_sql` and HR API contract tests assert exact 12/5 balances. |
| T07 | `integration/test_rag.py::test_real_filtered_cosine_sql`, plus the poison nearest-unfiltered-vector test, execute real pgvector cosine SQL on real normalized vector(384) embeddings. |
| T08 | `integration/test_rag.py::test_unpublished_or_stale_index_never_retrieved` covers status, source/index version and provenance changes. |
| T09 | `integration/test_multitask.py::test_triple_intent_uses_real_tools_and_keeps_results_without_booking`; independent reads use separate real concurrent DB connections. |
| T10 | `integration/test_midrun.py::test_true_midrun_note_same_id_and_no_repeated_read`: a real asynchronous pause overlaps the instruction HTTP request. |
| T11 | Mid-run revision race and date-amendment tests preserve original text, old completed results and traces; stale revisions get 409. |
| T12 | `integration/test_sse.py::test_live_heartbeat_note_terminal_and_disconnect` and explicit failed/cancelled terminal cases. |
| T13 | SSE replay/cursor, multi-batch and simultaneous-subscriber tests; frontend reducer tests reject duplicate IDs and stale generation text. |
| T14 | `integration/test_confirm.py::test_create_repeat_confirm_and_duplicate_exactly_once` and the browser smoke assert zero bookings/debits before the human confirmation click. |
| T15 | The same confirmation test and browser smoke assert one 3-day booking and a 12-to-9 balance change under the fictional calendar. |
| T16 | `integration/test_confirm.py::test_concurrent_duplicate_confirmation` and sequential API/browser duplicate checks. |
| T17 | Confirmation stale/expiry tests include expiry after waiting for a balance lock. |
| T18 | `security/test_proposals.py::test_other_tenant_or_same_tenant_hr_cannot_access_proposal`. |
| T19 | `integration/test_confirm.py::test_distinct_proposals_serialize_on_balance_and_revalidate`: competing proposals serialize and cannot overdraw. |
| T20 | HR validation and confirmation overlap/payload tests reject overlapping dates without partial mutation. |
| T21 | New `security/test_sql_injection.py`: actual SQL-looking search input, forged UUID and authority query input leave users, balances and policies unchanged. |
| T22 | New `integration/test_multitask.py::test_retrieved_confirmation_directive_never_dispatches_a_write`: a fictional fixture directive containing `confirm_leave` reaches the actual model spy, but only the authorized policy tool executes and business rows remain identical. |
| T23 | Isolation, policy, HR, task and proposal tests reject forged company, role, user ID, plan and approval fields. |
| T24 | `integration/test_midrun.py::test_restart_fences_old_worker_and_reuses_checkpoints`; isolated Docker restart preserves the same persisted task and identical SSE replay. |
| T25 | Mid-run cancel and SSE cancellation tests stop pending work, preserve the original and emit a cancelled terminal. |
| T26 | `security/test_isolation.py` and proposal CSRF tests cover absent/forged/expired sessions, cookie flags, exact Origin, token binding, logout and disabled identities. |
| T27 | `security/test_policy_api.py::test_employee_cannot_ingest` and ingestion CSRF/provenance-spoof tests. |
| T28 | `security/test_poison.py::test_empty_authorized_scope_returns_insufficient_sources` and retrieval threshold/no-source tests. |
| T29 | New `integration/test_resilience.py` uses a real refused TCP connection and a genuinely absent model directory, then verifies recovery/failure, sanitized logs, terminal status and no booking. Existing final-write-failure tests prove atomic rollback. The Docker audit also stops/restores its own DB and verifies a subsequent task completes. |
| T30 | `integration/test_frontend.py::test_browser_workspace`: real Edge + Vite proxy + API/SSE, controllably paused FakeLLM, enabled composer, same task ID, human-only confirmation, permission feedback and mobile layouts. |

## Reproduced failures and scoped fixes

- Queue polling allowed a DBAPI exception to terminate its supervisor. The real
  refused-connection test reproduced a task remaining queued after connectivity
  was restored. Polling now retries with a static sanitized warning. Worker
  heartbeat/DB failures preserve fenced leases for recovery rather than leaking
  exception/SQL details or claiming a durable failure while DB storage is down.
- Missing embedding assets were validated only after heavyweight Torch/model
  imports. The missing-directory task exceeded the regression's completion
  bound. Asset validation now runs before those imports, fails promptly and
  persists a failed task/terminal with no booking or debit.
- Default access logging included policy-search queries. This was reproduced with
  a private query canary. Packaged Uvicorn access logging now strips query strings
  and client addresses while preserving method/path/status; Nginx logs only
  equivalent request metadata. Two unit tests and the actual Docker search-query
  canary check cover this change. The backend Docker allowlist was updated to
  include the new logging configuration after the first rebuild exposed it.
- The Windows Docker harness initially decoded build output with cp1252 and hit
  Unicode reader errors. It now captures UTF-8 with replacement. This changes
  test output handling, not application requirements.
- SQL-looking input and a retrieved booking directive were coverage gaps; new
  adversarial tests exercise them without changing source assignment facts.
  Additional poison text exists only in disposable fictional test fixtures.

No assertions, authorization predicates, append-only guards, vector queries,
real embeddings or transaction tests were disabled or weakened.

## Reproduction and isolation

`scripts/verify_demo.sh` runs backend lint/format/dependency checks, clean frontend
install, typecheck, reducer tests, build and the full disposable-DB suite. Use
`--docker` to also build/start/restart an isolated stack. On Windows it supports
Git Bash and `.venv/Scripts/python.exe`; individual commands work in PowerShell.

`scripts/verify_phase2.py` removes OpenAI/Gemini/Hugging Face credentials and sets Hugging Face
and Transformers offline. The pinned MiniLM revision and asset checksums remain
unchanged. Real-model tests assert 384 dimensions and normalization; vector
ranking uses `<=>`. Poison checks inspect captured context, not merely a final
answer that could happen to omit leaked text.

`scripts/verify_phase11_docker.py` generates a unique `phase11_<uuid>` project,
temporary credentials and free host ports. Its volumes/networks are separate
from existing dev/test services. It builds API/UI, migrates/seeds/indexes only
that stack, checks the UI proxy and real policy answer, restarts API/UI, verifies
old-session rejection and byte-identical persisted SSE replay, then tests DB
outage recovery. It scans API/UI/DB logs for password, session-secret and private
request canaries and removes its containers/volumes in `finally`. Build images
may remain cached. Existing `.env` and persistent dev/test data are untouched.

## Known limitations

- A first synchronous policy-search request on a cold container exceeded the
  audit client's 20-second timeout under concurrent verification load. The normal
  asynchronous task workflow handles cold model initialization; the log audit
  then checks synchronous search after that real initialization, without raising
  the HTTP timeout or dropping retrieval/privacy assertions. No low-latency
  cold-start guarantee is claimed.
- FakeLLM is a bounded deterministic demo adapter. There is no general live LLM;
  answer deltas are chunks of a completed answer, not live token streaming.
- Authentication uses one process's in-memory session store. API restart requires
  sign-in again; the sidebar's current-sign-in history also resets on refresh.
- A fully unavailable DB cannot record a terminal failure immediately. The queue
  retries and expired leases recover after reconnection. Interrupted reads with
  no completed checkpoint can repeat; no autonomous booking writes exist.
- The service database credential is trusted and can bypass tenant RLS. All
  externally exposed queries still enforce server-derived tenant/visibility/self
  rules; this is not a separate least-privilege production DB-role deployment.
- Weekday-only leave counting is explicitly fictional, with no holiday calendar
  or manager approval system. All real booking effects require explicit owned,
  versioned, transactional confirmation.
- Log checks prove absence of the tested canaries, not universal PII absence.
  Packaged access logs contain request paths/statuses and task IDs. For local
  Uvicorn launches, also pass `--log-config backend/logging.json` when using
  `--app-dir backend`; the unconfigured Uvicorn default logs query strings. HTTPS, distributed
  sessions, load testing and production operational hardening remain outside
  this demo verification.
- Existing Starlette/httpx deprecation and Node 22 type-stripping warnings remain.
  The oversized-token test intentionally emits a tokenizer diagnostic.

Observed final command results are recorded below after execution.


## Observed commands

| Command | Observed output |
| --- | --- |
| Baseline `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | `332 passed, 1 warning in 263.66s`; no skips. |
| New failure regressions before fixes | `2 failed in 44.16s`: connection refusal prevented queued work from recovering, and missing assets were checked after heavy imports. |
| New failure regressions after fixes | `2 passed in 10.40s`; no skipped cases or relaxed assertions. |
| Adversarial real-vector/context subset | `25 passed, 1 warning in 75.18s`; includes SQL-looking text and the new retrieved booking directive. |
| Full post-fix `.\.venv\Scripts\python.exe scripts/verify_phase2.py` | `336 passed, 1 warning in 230.83s`; no skips, including browser smoke and all real-model tests. |
| `ruff check backend scripts` / `ruff format --check backend scripts` | `All checks passed!` / `89 files already formatted`. |
| `python -m pip check` | `No broken requirements found.` |
| Git Bash `bash -n scripts/verify_demo.sh` | Exit 0. |
| `git diff --check` | Exit 0. Implementation files remain untracked; no commit was made. |

The initial Docker run built both images and passed startup/indexing, restart,
UI/API policy retrieval and log-canary checks. Its Windows output-decoding issue
was fixed for the final repeatability run, which additionally exercises an
actual stop/start of only its own database. Final wrapper output follows.


The repeatability wrapper's second full suite passed `336 passed, 1 warning in
237.90s`, with a clean `npm ci` (0 vulnerabilities), 6 frontend tests, typecheck
and build (1.05s). Its Docker stage then found the newly added `logging.json`
was excluded by the backend's deny-by-default `.dockerignore`. The allowlist
was fixed and the isolated Docker component rerun; this was a packaging failure,
not a test assertion removed or bypassed. The two new log-safety tests separately
passed `2 passed in 0.17s` before the final full suite.


## Final results

- `.\.venv\Scripts\python.exe scripts/verify_phase2.py`: **`338 passed, 1 warning in 290.51s`**, exit 0, no skips. This final run includes the log-safety tests, real offline MiniLM/pgvector, all security and race tests, and the real browser smoke. Prior complete post-fix runs passed 336 tests twice before the two log tests were added.
- Frontend clean install audited **0 vulnerabilities**; typecheck passed; **6 tests passed**; production build passed in **1.05s** (32 modules; JS 239.36 kB, CSS 9.65 kB).
- Final Ruff: **`All checks passed!`**, **`91 files already formatted`**. Dependency check and whitespace check passed.
- `.\.venv\Scripts\python.exe scripts/verify_phase11_docker.py`: exit 0 with the output below, including the new query canary in the log assertions. The synchronous-search audit runs after the async task's genuine cold model initialization; no request timeout or safety assertion was weakened.

```text
Docker: api + frontend images built
Docker: clean isolated startup, migrations, seed and real local index passed
Docker: UI proxy, keyless policy SQL, restart/SSE persistence and real DB-outage recovery passed
Docker: logs contain no tested password/session-secret/request canaries
{"project": "phase11_bac543fc6e9740bdad92cf49ce4dccc9", "result": "passed", "persistent_dev_data": "untouched"}
```

The log-canary assertion includes the generated DB password, seed password,
session secret, private task request marker **and private search-query marker**.
The successful Docker project was removed in `finally`, including its volumes.
The existing dev/test services and `.env` remain unchanged. No Phase 12 work,
production deployment, migrations of persistent databases or commit was made.
