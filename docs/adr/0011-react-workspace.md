# React tenant workspace (Phase 10)

Status: accepted, 2026-11-09.

The frontend is a React/Vite/TypeScript application. A same-origin `/api` proxy
preserves the existing HttpOnly session cookie, exact Origin validation and CSRF
headers. Vite proxies during development; Nginx serves the build and proxies
without SSE buffering in the optional Docker `ui` profile. API and frontend
host ports remain configurable. The browser never supplies tenant or role
authority: the header displays identity returned by login.

Credentials are sent only to the existing login endpoint. Session display data
and CSRF token remain in memory. Sign-out clears conversation, task, source and
proposal state; 401 returns to login, and 403/404 clears an inaccessible selected
task with a useful error. The existing API has no session-inspection or
conversation-list endpoint, so sidebar history is scoped to the current sign-in;
refresh requires signing in again. Tasks and instructions remain persistent in
the backend. This phase does not add backend discovery/auth endpoints.

The composer stays editable while a task runs. Sending during an active task
posts an append-only instruction with its expected revision and client note UUID.
It retains the task ID and exact original request. Terminal tasks start a new
task in the selected conversation. Enter sends and Shift+Enter inserts a line;
IME composition is respected. Running/cancelling states and explicit task stop
are visible. Revision conflicts retain the draft and refresh the snapshot.

The SSE hook uses fetch streaming so it can distinguish authorization errors,
handle 204, send Last-Event-ID and abort on navigation/sign-out. Reconnects resume
from the last applied ID with bounded backoff. The pure reducer ignores duplicate
IDs and other tasks, clears generated text on newer instruction revisions and
ignores stale generation text. Snapshots supply authoritative completed answers,
source references and proposal details without concatenating a replayed answer
twice. Backend deltas still represent chunks of completed FakeLLM output, not
live-model tokens. Tool statuses and connection/reconnect state remain visible.

Source excerpts render as React-escaped text with citation/provenance labels.
No retrieved HTML, links or instructions become executable UI content. Source
access is still enforced by the API. The responsive workspace has keyboard
focus indicators, associated form labels, status/alert regions and mobile
conversation navigation.

Leave actions are explicit: preparing a proposal invokes the existing validation
and proposal endpoint; only clicking Confirm booking invokes confirmation with
the current proposal version. Cancelling a proposal is separate. Pending cards
show server-calculated days, expiry and the fictional weekday-only convention.
No model response or effect hook creates or confirms leave. Conflicts refresh
the proposal rather than retrying a booking automatically.

Reducer/parser tests use Node's built-in test runner. The browser smoke launches
temporary Vite and API servers against a disposable migrated/seeded PostgreSQL
database, and uses Playwright with installed Edge on Windows (Chromium elsewhere).
An actual FakeLLM pause proves in-flight same-ID notes; DB assertions prove no
booking before a click and exactly one 3-day debit afterward. Test-only release
and inspection routes exist only on this ephemeral test app. Tests also exercise
tenant switch, permission errors and mobile layout; screenshots are ignored.

No production backend logic, schema, agent behavior or later phase is changed.
