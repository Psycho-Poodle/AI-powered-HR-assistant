# ADR 0007: Typed DAG execution with a deterministic demo LLM

Date: 2026-11-08
Status: Implemented for Phase 6 only.

## Planning and tool authority

Use a small LLM protocol with async plan/compose methods and deterministic
`FakeLLM`, not a graph framework or live provider. The fake parser recognizes
the demo's balance, policy, profile, history and dated-leave intents. It is a
bounded rule-based adapter, not a general natural-language understanding claim.
Missing/ambiguous dates produce clarification; no dates are invented from a
requested number of days. Unsupported mutations have no registered tool.

Pydantic discriminated step models permit only the five existing self-only HR
read/validation and authorized policy tools, plus logical talk/refusal/clarification
steps. Tool arguments have no actor, tenant, role, SQL or booking fields. Plans
have at most eight unique nodes; missing dependencies and cycles fail validation
before dispatch. Model plans are revalidated at the boundary. Server-side demo
target guards refuse explicit other-company policy requests or other-person HR
requests while retaining independent permitted branches. SQL authorization remains
mandatory regardless of parsing; the model never establishes identity or rights.

## Execution and context

Execute ready DAG waves with asyncio gather. Blocking SQL/model calls use threads,
and every read has its own connection/transaction and rechecks the active actor
and company. HR tools use READ ONLY transactions. Policy reads use ordinary
transactions because PostgreSQL disallows their final shared policy locks in a
read-only transaction. They still call only the existing authorized read tool.
Validation depends on a successful balance read; failed dependencies skip future
work without discarding independent successes. Exceptions become sanitized tool
codes, never raw SQL, credentials or exception text in the response.

Results retain the exact original request, validated plan, ordered subtask outputs,
tool status transitions and final answer/outcome. Results are ordered by plan;
trace order reflects actual execution and can differ between concurrent runs.
Composition runs once after execution, not in an autonomous tool-feedback loop.
The deterministic composer reports balances, citation-grounded assignment
attendance sentences, permitted references, validation results and clarifications.
Other policy subjects remain structured evidence rather than a claim of general
language generation. It does not obey or reproduce poisoned
document directives as instructions. Structured policy evidence remains available
as untrusted data in the subtask result.

Before composition, recheck actor activity/role and policy source access/version/
hash. Revoked policy sources are removed from the adapter input. Actor revocation
clears payloads and prevents composition. Task replay also rechecks policy access
and suppresses the stored answer when source access changed, without rewriting
the stored original request. This avoids turning persisted results into a policy
authorization bypass. A future live composer must preserve this boundary.

## Minimal persistence and HTTP behavior

Use existing conversation, message and task tables; no migration is needed.
Create a task with immutable original_request, then persist execution snapshots
in Task.plan as statuses change and when composition finishes. Only conversation/
message/task metadata is written. Leave balances, requests, proposals, history
and audit rows are not modified. Task messages/events are reserved for later phases.

Provide POST `/api/v1/conversations`, GET `/conversations/{id}`, POST
`/conversations/{id}/tasks` and GET `/tasks/{id}`. Every object lookup is scoped by
actor company and owner. Existing Origin/CSRF protections apply to POSTs; injected
plans/identity fields are rejected. Serialize task creation on the conversation
row and reject a second active job with 409.

The task POST executes in the foreground and returns HTTP 200 with the finished
execution state, rather than claiming 202 background execution. `status` describes
whether execution finished/failed; `outcome` additionally distinguishes partial
success, clarification and refusal. A completed read needing dates is not an
awaiting-confirmation proposal. HTTP 202 queueing, durable leases, interruption,
restart recovery and SSE remain Phase 8/9 work. A process interruption can leave
a task running until operator resolution; this phase makes no durability/recovery
claim. No mid-run instruction or cancellation API is added.

## Verification

Unit gates prove independent reads both start before either completes. Real DB
tests additionally hold two PostgreSQL connections at a barrier and verify
different backend PIDs. Committed fixtures are needed for separate connections;
they are created/removed only in the runner's guarded disposable database.
Tests cover triple intent, date clarification, DAG validation, dependency skips,
partial failures, composition failure, poison/context isolation, source and actor
revocation, ownership/spoofing and original-request persistence. Business-table
snapshots prove read/validation execution does not book or debit leave.

Phase 7 proposal/confirmation and later phases require separate authorization.
