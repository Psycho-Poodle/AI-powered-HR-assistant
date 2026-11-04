# DOCUMENT 6 — Test Strategy and Acceptance Criteria

## 1. Test infrastructure

Use `pytest`, `pytest-asyncio`, `httpx.AsyncClient(ASGITransport)`, real disposable PostgreSQL with pgvector via Docker Compose or Testcontainers, real `SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')`, deterministic `FakeLLM` implementing tool-intent and streamed text protocols. No OpenAI/Gemini API key is required. Download/cache model assets once during image build; tests operate offline thereafter. Make model version and random seed fixed. Separate `db_test` from development database; migrate/seed fresh per test session with isolated data or transactions per test. Mock only the LLM/network adapter, not embeddings/vector SQL.

```bash
docker compose up -d db_test
python -m pytest -q tests/unit
python -m pytest -q tests/integration
python -m pytest -q tests/security
```

Commands are target commands for future implementation, not evidence that the project has been implemented or tested.

## 2. Test matrix

| ID | Test | Fixture/action | Required result |
|---|---|---|---|
| T01 | Summit/Pebble isolation | Maya queries Pebble late rule | zero Pebble rows/snippets/answer exposure |
| T02 | Reverse isolation | Ravi queries Summit | zero Summit exposure |
| T03 | HR tenant boundary | Leila queries Pebble | denied, despite HR role |
| T04 | CEO document ACL | Maya vs Leila query salary band | Maya denied/not in LLM context; Leila permitted |
| T05 | Poison injection | Maya asks about lateness, poison retrieved | correct Summit answer; no Pebble handbook/pay leaks |
| T06 | Leave SQL | Maya/Ravi query balances | exactly 12/5 from SQL, no RAG |
| T07 | Real vector retrieval | embed query+docs; execute `<=>` in pgvector | proper company policy among top results |
| T08 | Policy status/version | draft/retired policy present | unpublished content excluded |
| T09 | Multi-intent | balance + late policy + leave preparation | distinct authorized subtask calls; results aggregated |
| T10 | Mid-run update | pause fake LLM/tool, post note | same task ID; original preserved; revised pending work |
| T11 | Conflicting update | new note changes style/scope | latest allowed note applies to unfinished work, old trace remains |
| T12 | SSE progress | subscribe to job | ordered start/tool/delta/end events; no missing terminal state |
| T13 | SSE replay | reconnect `after=N` | only events `>N`, no duplicate text |
| T14 | Proposal no write | request 3 days | proposal exists; balance 12, no leave_request |
| T15 | Approve | confirm valid proposal once | one leave row, 9-day Maya balance under chosen demo calendar |
| T16 | Duplicate confirm | confirm twice concurrently/sequentially | exactly one booking; second 409/idempotent lookup |
| T17 | Expired/stale proposal | time travel/version change | 409, no balance change |
| T18 | Other employee proposal | Ravi confirms Maya's | 404/403, no mutation |
| T19 | Insufficient days/races | two concurrent requests exceed balance | at most one approved, no negative balance |
| T20 | Overlap | overlapping leave periods | denied without partial mutation |
| T21 | SQL injection | malicious query string / IDs | treated as data, no database changes |
| T22 | Tool injection | retrieved text requests `confirm_leave` | tool never invoked from policy content |
| T23 | Tenant ID spoof | browser submits `company_id=pebble` as Maya | ignored/rejected, remains Summit |
| T24 | Restart recovery | terminate runner between checkpoints | no duplicate writes; recovered or explicit failure |
| T25 | Cancel | cancel running task | pending work stops, terminal event, original preserved |
| T26 | Auth/cookie security | missing cookie, CSRF attempt | denied, no writes |
| T27 | Document ingestion ACL | employee attempts HR document upload | denied |
| T28 | Empty/no-match RAG | query out of scope | graceful insufficient-source response; no invented policy |
| T29 | Errors | DB down or embedding failure | task.failed, actionable UI, no silent partial booking |
| T30 | UI mid-run note | browser E2E on active task | composer stays enabled, notes attach to same job |

## 3. Deterministic mid-run test technique

Fake tool/LLM has an `asyncio.Event` gate: test sends original request; waits for `tool.started`; posts additional instruction while the gate holds; releases gate; asserts task ID unchanged, `original_request` unchanged, incremented revision, updated plan and final answer reflecting both instructions. This is a real concurrency test, not two sequential chat requests pretending to be simultaneous.

## 4. Security assertion that actually matters

Test the contents of **retrieved context supplied to fake LLM**, not only the final response. If confidential or cross-tenant content enters the context but the fake model happens not to repeat it, isolation has already failed. Capture tool outputs and model input context in test-only spy, assert sensitive doc IDs/text absent for unauthorized actor. Conversely verify allowed Leila context includes Summit HR document.

## 5. Definition of acceptance

- All 30 scenarios represented by automated tests where feasible, with mandatory T01–T07, T09–T10, T12, T14–T18 green.
- Tests run without external LLM API key; true Postgres/pgvector and real embedding model used in integration pipeline.
- `docker compose up --build` works after documented environment setup and starts demo UI/API.
- Demo of three identities, multi-intent, mid-run message, policy injection prevention and confirm-only leave booking is reproducible.
- No secret committed; lint/typecheck and integration tests pass; README truthfully reports limitations and **actual hours logged**, not an estimate invented afterward.

## 6. CI recommendation

Run backend lint (`ruff check`), formatting (`ruff format --check`), optional `mypy`, frontend `tsc --noEmit` and build, unit tests, Docker service integration tests. Cache local embedding weights while pinning hashes; no external LLM calls. Add Playwright UI smoke test if time allows. Gate submission on deterministic repeatability (run integration suite twice).
