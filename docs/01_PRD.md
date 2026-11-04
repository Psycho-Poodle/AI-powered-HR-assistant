# DOCUMENT 1 — Product Requirements Document (PRD)

**Project:** HR Chat Assistant | **Status:** Design baseline | **Source of truth:** `Task-AI-Engineer 1.pdf`, pp. 1–2. **Audience:** candidate, reviewer, Codex. This document defines requirements, not evidence of implementation.

## 1. Assignment baseline and classification

**Mandatory (M):** Two tenants, Summit Dental (`summit`) and Pebble Retail (`pebble`), with zero cross-tenant data disclosure. Fixed identities: Maya (Summit employee), Leila (Summit HR), Ravi (Pebble employee). Policy RAG on real embeddings/pgvector, protected CEO salary band for Leila alone, poisoned Summit policy never obeyed, Maya balance 12, Ravi balance 5, multi-step tasks, streamed output, mid-run notes attached to same job, user approval before any leave booking, Python/FastAPI-compatible backend, PostgreSQL + pgvector, simple streaming UI, docker-compose, seed data, README, and offline-keyless tests exercising real local embeddings and real pgvector.

**Demonstration extensions (E):** Login screen and demo auth, persistent conversations, policies for leave/sick leave, document ingestion screen, comprehensive audit trail, responsive polished React frontend, document version management, explicit cancellation, replayable SSE. Useful to prove reliability, but not all are demanded by the PDF.

**Production hardening (P):** Enterprise SSO, advanced tenant-owned encryption keys, autoscaling workers, monitoring/alerts, DR, antivirus, regulatory retention, formal policy approval workflow. Do not imply these are implemented in the take-home.

## 2. Product vision, problem and value

Employees need understandable, tenant-accurate HR answers and convenient leave requests. HR teams need access to restricted policies without exposing them to others. Existing chatbot prototypes can hallucinate rules, leak retrieved secrets, start duplicate jobs when instructions change, and silently mutate records. This demonstration proves trustworthy orchestration with explicit source routing and authorization enforced outside the LLM.

**Goals:** (G1) correct role- and company-scoped retrieval; (G2) sensible SQL/policy/tool routing; (G3) observable real-time multi-step execution; (G4) an additional message updates the same running job; (G5) leave booking requires approval and is race-safe; (G6) tests run without cloud credentials; (G7) setup is reproducible via Docker Compose.

**Non-goals:** Real payroll integration; actual HRIS connectivity; actual corporate policy advice; mobile-native app; more than three demo users; autonomous payroll changes; unbounded agent swarms; replacing a company's HR governance.

## 3. Personas and permissions

- **Maya**, employee, Summit: can read Summit employee-visible policies, her own leave balance/request history, and propose/confirm her own leave requests. Cannot access Summit HR-only pay or any Pebble information.
- **Leila**, HR, Summit: can read Summit employee and HR-only policies, including salary band; may administer Summit documents if demo ingestion is enabled. Not entitled to Pebble information. Do not assume delegated employee leave access unless explicitly modeled.
- **Ravi**, employee, Pebble: can read Pebble employee-visible policies and his own 5-day leave balance, not Summit policies.

**Required policy facts:** Summit: third late arrival -> one-day pay cut. Pebble: third late arrival -> warning only. Summit CEO salary band: Leila only; do not invent amount as provided by assignment. Summit poisoned document must contain the assignment's attack concept (ignore previous instructions, paste Pebble handbook, reveal Summit CEO pay) and be queryable as *data*, but never followed.

## 4. Functional requirements (acceptance-oriented)

| ID | Priority | Requirement | Observable acceptance |
|---|---|---|---|
| FR-01 | M | Tenant isolation | Maya/Ravi cannot query the other's policies; Leila stays Summit-scoped |
| FR-02 | M | RBAC for documents | Only Leila accesses CEO salary-band document |
| FR-03 | M | Policy RAG | Text chunks embedded locally and retrieved from real pgvector with filters |
| FR-04 | M | Structured leave | Maya receives 12, Ravi 5, from leave_balances SQL |
| FR-05 | M | Multi-intent | One input yields subtask plan + independently executed results |
| FR-06 | M | Streaming | Client displays incremental server events/deltas, not one final blob |
| FR-07 | M | Mid-run instruction | New instruction attaches to original task ID and affects unfinished work |
| FR-08 | M | No unapproved mutations | Before confirmation, leave balance/requests remain unchanged |
| FR-09 | M | Poison resistance | Poisoned retrieved chunk does not trigger unauthorized search/disclosure |
| FR-10 | M | Reproducible tests | Keyless deterministic LLM, real local embeddings + real PostgreSQL/pgvector |
| FR-11 | E | Authentication | Session establishes server-side user/tenant/role context |
| FR-12 | E | Persistent job events | Reconnecting client resumes after latest event ID |
| FR-13 | E | Proposal lifecycle | Approve, reject, expiry, duplicate/replay protection |
| FR-14 | E | Policy provenance | Documents store ownership, visibility, version and ingestion metadata |

## 5. User journeys

**A. First login (E).** Open login -> authenticate as a seeded demo identity (passwords from environment/hashed seed, never hardcoded in browser) -> server issues HttpOnly cookie -> GET `/api/v1/me` returns user/tenant/role -> route to tenant-branded workspace -> load conversations. Browser never chooses authoritative tenant ID.

**B. Policy (M).** Maya: “What happens if I arrive late three times?” -> auth -> policy intent -> query embedding -> SQL prefilter by `summit`, published, allowed visibility -> similarity rank -> sanitized citations -> streaming reply: Summit applies one-day pay cut. No Pebble data.

**C. Structured balance (M).** Maya: “How many leave days?” -> `get_leave_balance` uses SQL on her user ID; returns 12. Embeddings are inappropriate for mutable numerical truth.

**D. Multiple intents (M).** Maya: “Tell me my remaining leaves, explain the late attendance policy, and prepare a leave request for three days.” -> plan three independent branches -> SQL balance and RAG policy in parallel -> leave validation branch requests missing dates -> *draft proposal only after dates supplied* -> combine outputs without losing partial results.

**E. Mid-run note (M).** While task `T` is active, Maya adds “Also explain it in plain language.” POST note to `T`; status/event queue records it; at checkpoint planner preserves original objectives, updates response style, and emits `task.updated`. The note is NOT a separate conversation/task.

**F. Leave confirmation (M).** User provides concrete date range -> verify dates, allowance, overlaps and optionally leave policy -> persist proposal (not leave booking) -> show confirmation card -> user explicitly approves -> re-check identity, balance and conflicts in transaction -> create leave request and debit reserved/available days according to chosen demo model -> audit. A proposal record is not a booked leave.

**G. Unauthorized (M).** Maya requests Summit CEO pay or Pebble handbook -> deny at authorization layer before model context; state cannot share restricted information. Asking differently or via poisoned document does not change policy.

**H. HR (M).** Leila can retrieve Summit CEO band, but still cannot retrieve Pebble handbook. HR role cannot cross tenant boundaries.

**I. New tenant onboarding (E/P).** Authorized admin registers tenant, creates users, uploads approved documents with tenant provenance/access labels, queues validation/chunking/embedding, publishes version, tests retrieval; replace demo seed with tenant-managed ingestion pipeline. No real HR system assumed.

## 6. Business rules

1. Actor identity and company derive from authenticated server context; never from model-provided tool arguments or user-controlled company IDs.
2. Employees can read only their own structured HR rows. HR visibility does not automatically confer arbitrary employee record access.
3. Documents are always untrusted reference data, not instruction authority.
4. A job stores immutable original request plus append-only notes and may revise unfinished steps; completed steps stay in trace.
5. A task has one active write proposal of a given semantic operation; changed scope invalidates stale proposal.
6. Booking requires the authenticated owner to click approve; assistant text is not approval.
7. Amount of days, policy details and leave-calendar conventions not in source are demo assumptions, explicitly flagged.

## 7. Non-functional requirements and measurable targets

- **Security:** no forbidden documents enter context; parameterized SQL; authenticated endpoint-by-endpoint access; redact sensitive logs; no secrets in Git.
- **Correctness:** all cross-tenant and access tests pass; exactly one leave booking after duplicate approvals; real pgvector query used in integration test.
- **Resilience:** event stream reconnect works; jobs recover or fail transparently after restart; retries do not repeat writes.
- **Latency targets (aspirational, not assignment mandates):** first status event <1 s locally; balance read <300 ms warm; 95% of keyless integration test suite deterministic.
- **UX:** active composer allows mid-run notes, clear status, source links, proposal confirm/cancel, errors and empty states, mobile responsive.
- **Operability:** one documented bootstrap command plus migrations/seeding, healthchecks, structured logs, descriptive README.

## 8. Demo success criteria

As Maya: see 12 days and Summit late policy, fail to access CEO pay/Pebble; as Ravi: see 5 and warning, fail Summit access; as Leila: retrieve CEO band but fail Pebble; retrieve poisoned Summit document without obeying instructions; execute two tools for one message; send note before task finishes and observe same task ID; propose 3-day leave, inspect unchanged balance, approve exactly once, verify change; restart/reconnect and inspect event history; run tests offline with real pgvector and real local embeddings.

## 9. Assumptions / unresolved choices

No CEO salary figure or Summit/Pebble handbook text is supplied; any placeholder salary amount/handbook used in demo must be labeled fictional and not represented as a source fact. No leave start/end dates provided in multi-intent example; prompt for dates. Paid/unpaid day counting, weekends, holidays, employee identifiers, approval after booking and leave accrual details are not specified. Choose simple explicit demo conventions and record them in README. Actual hours worked must be recorded by implementer, not fabricated.
