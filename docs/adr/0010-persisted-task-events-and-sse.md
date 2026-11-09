# Persisted task events and authenticated SSE (Phase 9)

Status: accepted, 2026-11-09.

The existing append-only `task_events` table is the replay log. Event payloads
are a validated discriminated union: `task.status`, `task.updated`, `tool.status`,
`assistant.delta`, `proposal.updated` and `task.terminal`. Each envelope carries
the task ID, per-task sequence and instruction revision. No model can supply
event authority, task ownership or event sequence numbers.

Writers lock the task row before allocating `max(seq)+1`. The existing unique
constraint on `(task_id,seq)` remains a second guard. Stable task-scoped UUID
retry keys suppress repeated checkpoints and recovered-worker notifications;
conflicting reuse fails. Rolled-back writes consume no sequence. Events commit
in the same transaction as queue creation, notes, status changes, execution
checkpoints, final assistant messages or proposal transitions. Lease checks
still precede worker writes. Proposal mutation locks now consistently acquire
task before proposal/balance to avoid lock inversion with note invalidation.

Migration `0005_event_baselines` adds a status/terminal baseline for preexisting
tasks with no log. It does not recreate historical tool/text events. Downgrade
preserves the append-only rows. Deployments must apply migrations before
starting the updated API; validation applies them only in disposable test DBs.

`GET /api/v1/tasks/{id}/events` requires the signed session cookie and current
database identity. Other users, including same-company HR, receive 404. Every
poll rechecks the session, active user/company and owner/company scope. No
request-scoped database dependency is held open through the response. Each
subscriber uses independent short transactions and its own cursor. Disconnects
close only the subscription; task execution continues. Logout, expiry or
revocation after response headers closes the stream without private payloads.

Numeric `Last-Event-ID` takes precedence over optional `?after=N`. Both supplied
values must be valid nonnegative signed-bigint-range decimal cursors; ahead-of-
log values return 422. Replay returns only committed events with `seq > cursor`
in ascending batches of 100. All data frames have numeric `id`, typed `event`
and JSON `data`; embedded text newlines are escaped. Fifteen-second heartbeat
comments have no ID and are not persisted. Responses disable caching and proxy
buffering. Polling is bounded at 100 ms rather than requiring another broker.

Completed, failed and cancelled executions append an explicit `task.terminal`.
The stream closes after draining the current log of a terminal task. Reconnect
at its last event returns 204 to stop EventSource retries. Human proposal
changes can append further events after execution finishes; a reconnect then
reads these newer events and closes again. Subscribers never write, acknowledge,
delete or consume events on behalf of other subscribers.

FakeLLM currently returns complete strings. Answer deltas therefore split the
finished answer into at most 512-character fragments and commit them with the
terminal checkpoint. Tool progress and notes stream while execution runs; this
phase does not claim token-by-token model streaming. Historical answer deltas
retain policy ID/version/hash references internally. Replay rechecks every
reference against current tenant/visibility authorization and redacts a fragment
if any source is no longer permitted. Internal source metadata and document
text are not exposed in the event payload; sequence continuity is preserved.

Tests use real PostgreSQL and a temporary localhost Uvicorn server to observe
actual incremental frames, heartbeats, disconnects and simultaneous subscribers.
They also cover replay, cursor validation, duplicate append retries, rollback,
sequence allocation races, failed/cancelled terminals, revocation and migration
baselines. Frontend, browser reducer and live-model token integration remain
outside Phase 9.
