# ADR 0008: Owner-confirmed, exactly-once leave booking

Date: 2026-11-08
Status: Implemented for Phase 7 only.

## Proposal lifecycle

Use the existing action_proposals table for pending -> confirmed/cancelled/expired
transitions. Terminal proposals cannot be reused. Every transition increments
version; confirm/cancel require a positive strict expected_version integer.
Creation accepts an owned completed task and ISO annual-leave dates. Company and
owner come from authentication. Proposal payload records server-calculated days
and `fictional-mon-fri-v1`; clients cannot supply amount, owner, expiry or approval.
The Phase 5 fictional inclusive Monday-Friday convention remains unchanged.

Creation writes proposal metadata only, with a server-side 15-minute lifetime.
A task-row lock serializes creation: repeating the same active payload returns
the same proposal; different active payload returns 409. Expired pending proposals
can be transitioned and replaced. No balance, leave request, history or audit row
is created just by proposing. GET is owner-scoped and does not mutate expiry;
an action evaluates the deadline and commits expired status when applicable.

## Confirmation transaction

The HTTP endpoint derives CurrentActor from the existing authenticated session
and requires exact Origin and session-bound CSRF. A fresh mutation transaction
rechecks/locks active user and company, scopes and locks the proposal, checks its
state/version/action/task owner, then locks the actor's own balance. Database
clock_timestamp is evaluated after lock waits, including after the balance lock,
so time spent blocked cannot extend the proposal lifetime.

Reparse the stored typed payload and revalidate dates, amount, current balance
and own booked/pending-request overlaps. Pending proposals are not reservations.
On success, one transaction inserts a booked request referencing the unique
confirmed_proposal_id, debits/increments the locked balance, marks the proposal
confirmed/version+1, and appends leave history and a minimal audit record.
The fictional demo books immediately on confirmation; it does not model manager
approval or accrual. No implicit refund/cancellation of a confirmed booking exists.

The proposal lock serializes duplicate confirmations. The per-user balance lock
serializes different proposals so a later transaction sees the first booking and
balance change. The existing unique booking/proposal constraint is the final
duplicate guard. Sequential/concurrent replays return 409 rather than another
booking. An inner savepoint protects all booking effects if a caller catches an
error; the HTTP adapter commits the outer transaction before returning success.

Expected conflicts are returned as typed internal failure values, allowing an
expired-state update to commit before HTTP 409. Unexpected exceptions escape
and roll back the transaction. Ownership failures are non-enumerating 404s.
Cancellation locks and transitions only an owned pending proposal and appends
a cancellation audit; it never debits, books, refunds or changes leave history.

## Authority and scope

Creation, confirmation and cancellation are explicit authenticated HTTP actions.
The Phase 6 LLM registry and discriminated plan schema remain read/validation-only:
no confirmation, cancellation, booking or arbitrary SQL tool is exposed. This
phase does not add autonomous proposal creation to the planner. The caller can
create a reviewable proposal after validation, inspect it, then explicitly confirm.
Task execution state remains separate from proposal state. Mid-run notes, durable
leases/recovery, SSE and UI remain later-phase work.

## Verification

Real DB tests cover no booking/debit before confirmation, repeat creation,
duplicate/separate-proposal races, balance insufficiency and overlap after waiting,
confirm-versus-cancel races, stale versions, expiry while blocked on balance,
payload mismatch and rollback after an injected audit-write failure. HTTP tests
exercise owner/tenant/HR isolation, Origin/CSRF, forged fields, committed expiry,
cancellation and strict version tokens. LLM plan tests reject mutation tool names.

Each booking test uses a dedicated named database under the runner's isolated
test cluster. Append-only history/audit protections are never disabled or bypassed
for cleanup; only the guarded disposable database is dropped. Existing dev/test
data is not changed. No migration, new dependency or seed change was needed.
Phase 8 requires separate authorization.
