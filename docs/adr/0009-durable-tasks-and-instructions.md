# Durable tasks and in-flight instructions (Phase 8)

Status: accepted, 2026-11-08.

Task submission commits a queued task and its exact original request before
returning HTTP 202. Each application process runs a bounded two-worker polling
supervisor. PostgreSQL `FOR UPDATE SKIP LOCKED` claims queued tasks and expired
leases. A fresh random token and database-clock expiry fence every checkpoint,
renewal and terminal transition. Default leases last 30 seconds. Shutdown leaves
unfinished leases for recovery after expiry; it does not cancel the user's task.
This demo worker uses the existing trusted database service credential, which
can inspect the cross-tenant queue. It derives each actor from current database
identity, then uses the existing authorized repository tools.

Instructions append to the existing guarded `task_messages` table under the
owned task row lock. Revision increments and insertion commit together. Optional
`expected_revision` detects concurrent edits; optional `client_note_id` makes
retries idempotent, with conflicting reuse rejected. The new nullable UUID and
unique constraint require migration `0004_note_replay`. Original request and
append-only guards remain database-enforced. At most 64 notes are accepted.

Checkpoints run before tools, after results and before generation. A revision
change saves completed results and replans the same task. Finalization checks
the revision again under lock, so an older answer cannot win after an accepted
note. The deterministic demo planner retains original goals, merges additional
read goals, resolves supplied dates and supports plain/formal/brief style notes.
It remains bounded to eight typed steps; it is not arbitrary natural-language
instruction interpretation. Changed validation inputs receive a new operation
revision, while prior completed results remain inspectable.

Completed read results are keyed by tool, typed arguments and operation revision.
Recovery reuses checkpointed results, preserving statuses and trace. Interrupted
reads without a completed checkpoint may run again: exactly-once invocation of
external tools is not claimed. The registry exposes no booking mutations.
Terminal state and a deterministic, unique assistant message commit together.
Lease fencing prevents old workers from saving after recovery. Cached policy
sources are authorized again before model context and on task GET; internal
cache storage is excluded from the API response.

Cancellation takes the owned task lock, enters `cancelling` and invalidates
pending proposals. The worker stops at a checkpoint or during its composition
pause, then persists `cancelled`. Notes also invalidate pending proposals.
Confirmed bookings are never undone. Confirmation remains a separate explicit,
authenticated human endpoint; an already-winning confirmation may commit.

`FakeLLMPause` is an asynchronous one-shot gate controlled by thread-safe events.
Integration tests submit actual HTTP instructions while composition is blocked,
race revisions, cancel without releasing the gate, expire/reclaim a stopped
worker's lease and verify one task ID, one completed read and one assistant
message. SSE/event persistence and UI remain later phases.
