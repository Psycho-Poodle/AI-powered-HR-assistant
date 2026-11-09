# ADR 0006: Typed self-only HR reads and advisory leave validation

Date: 2026-11-08
Status: Implemented for Phase 5 only.

## SQL reads and authorization

Typed tools read balance, profile and history from SQLAlchemy queries scoped by
both server actor company and user ID. Optional tool subject IDs must equal the
actor; HR does not gain delegated employee access. HTTP inputs contain no subject,
company or role selectors. Existing balance response fields and Decimal encoding
are preserved; Leila's unspecified balance remains absent, never invented as zero.
Missing profile/balance raises `not_found`; another subject raises `forbidden`.

History uses bounded newest-first keyset pagination on `(occurred_at, id)`, so
equal timestamps neither repeat nor omit rows. The base64 JSON cursor holds only
a timezone-aware timestamp and UUID. It is an untrusted position, not a permission
token: every page independently applies the same self/tenant predicates.
Malformed cursors/limits produce predictable input errors. The original internal
history helper remains available; the typed tool uses the paginated query.

## Fictional validation convention

Count inclusive Monday-Friday days, without verified employer weekend rules,
public holidays, accrual or half-days. This is explicitly FICTIONAL DEMONSTRATION
CONVENTION in every validation result, not an assignment fact or legal entitlement.
Only annual leave is accepted; no sick-leave entitlement is inferred from annual
balances. Dates must be real ISO calendar dates; timestamps and numeric epochs
are rejected. Reversed ranges and ranges over 366 inclusive calendar days return
business validation errors. No future-date rule is invented by this phase.

Validation reads the current own balance and checks own booked/pending leave
requests for any inclusive calendar-date overlap. Cancelled requests and other
employees' requests do not block or disclose information. Pending action proposals
are not reservations and are not queried. Results include days, available balance,
an overlap flag and typed reason codes. Malformed request data returns HTTP 422;
a well-formed but invalid range returns HTTP 200 with `valid=false` and reasons.
Missing self records return 404; direct tools reject another subject with 403.

This is an advisory snapshot: no locks, reservation, proposal, booking, debit,
history or audit row is written. Future confirmation must recheck balance,
permissions, dates and overlap inside its write transaction. Phase 7 remains
separate; no validation result can count as approval.

## HTTP surface and verification

Preserve `/api/v1/leave/balance`, and add `/employee/profile`, paginated
`/leave/history`, and POST `/leave/validate` under `/api/v1`. Authentication derives
the immutable actor. The read-only POST still enforces existing Origin/CSRF checks.
Errors use the existing API envelope and stable tool reason codes.

Tests use real PostgreSQL for 12/5 balances, cross-tenant and same-tenant self
denials, HR restrictions, tied history pagination, inclusive overlap/status rules,
and row snapshots across all application tables. SQL capture proves validation
and reads emit SELECT statements only. Date/weekday/cursor unit tests are keyless.
Fixtures create fictional overlap/history rows solely inside rolled-back tests.
No schema, seed facts, RAG behavior or persistent dev/test data changes are needed.

No booking/proposal writes, generic agent orchestration, streaming or UI were added.
Phase 6 requires separate authorization.
