# ADR 0004: Server-derived identity and SQL-enforced authorization

Date: 2026-11-07
Status: Implemented for Phase 3 only.

## Identity and sessions

Use the existing Argon2id seeded passwords. Login accepts only username/password,
requires the configured browser Origin and resolves one active user in an active
company. Duplicate usernames across active companies fail closed rather than
trusting a browser tenant selector. Generic credential errors and dummy hash
verification avoid exposing username existence through response messages.

A cookie contains a random opaque identifier and HMAC signature, with no client
identity, tenant or role claims. Server memory holds the hashed identifier, user,
company, expiry and independent CSRF token. Cookies are HttpOnly, SameSite=Strict,
path `/api/v1`, and Secure by default. The local HTTP example explicitly disables
Secure. Session signing needs a random `SESSION_SECRET` of at least 32 characters;
the local ignored `.env` was supplied one without changing database passwords.

Successful login rotates the current browser session. Logout revokes server state
before clearing the cookie; expired, tampered, unknown and revoked tokens fail.
Use one API worker. Restart drops sessions; cross-process session durability,
enterprise SSO and production authentication hardening are not claimed.

## Authority boundary

On every protected request the dependency reloads active user/company/role from
SQL and constructs `ActorContext(user_id, company_id, role)`, a frozen slotted
dataclass. Disabling accounts/companies or changing a role affects the next
request. No request body/header/query/cookie field supplies an authoritative actor.
Protected unsafe methods require both exact Origin and a session-bound CSRF
header. Login checks Origin separately; logout accepts an empty body only.

Set `app.tenant_id` transaction-locally from the server session, and scope every
resource query independently. Policy text is selected only when tenant, published
status and visibility predicates pass. Specific-user visibility matches the
actor ID, so an HR role alone cannot access Leila's CEO source. HR scope never
crosses company boundaries. Balance/profile/history queries require both actor
company and own user ID; providing another subject cannot widen their scope.
Forbidden sources return no repository row and the same HTTP 404 as missing IDs.

Credential lookup necessarily precedes tenant context; the demo uses the existing
bootstrap DB connection for that lookup. Bootstrap RLS bypass is not considered
an authorization mechanism. Explicit SQL predicates are tested even with that
connection, alongside Phase 2 nonprivileged RLS tests. A separate least-privilege
credential lookup role/function remains future hardening.

## Scope and verification

Add login/logout/me, direct authorized policy reads, and one self-balance route
to exercise boundaries over HTTP. Profile/history reads are repository-only.
No policy search, embeddings, RAG, ingestion, leave validation/booking tools,
planner, streaming or UI is implemented. No schema migration was needed.

Security tests use real PostgreSQL and real password verification. They override
only connection lifetime to roll back fixtures, not auth or repository logic.
The disposable database runner now defaults to ports 5432/5433; those ports are
available and verified with Compose. Persistent dev/test data is not reset.
The existing runner name is retained and now includes all backend tests.

Phase 4 requires separate authorization after this phase stops.
