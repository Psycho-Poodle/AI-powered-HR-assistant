import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  initial,
  parseFrame,
  reduce,
  type Event,
} from "../src/hooks/events.ts";
import { friendly } from "../src/api/client.ts";

const event = (
  seq: number,
  revision = 0,
  payload: Record<string, unknown> = { text: "hello" },
): Event => ({ task_id: "a", seq, revision, payload });
describe("task stream reducer", () => {
  it("replays workflow once, clears on revision and isolates task switches", () => {
    const workflow = {
      kind: "leave_request",
      task_id: "a",
      origin_task_id: "a",
      revision: 0,
      status: "collecting_dates",
    };
    const first = reduce(
      initial("a"),
      event(1, 0, { workflow }),
      "task.workflow",
    );
    assert.equal(first.workflow?.task_id, "a");
    assert.equal(
      reduce(first, event(1, 0, { workflow }), "task.workflow"),
      first,
    );
    const revised = reduce(first, event(2, 1), "task.updated");
    assert.equal(revised.workflow, null);
    assert.equal(
      reduce(revised, event(3, 0, { workflow }), "task.workflow").workflow,
      null,
    );
    assert.equal(
      reduce(initial("b"), event(4, 0, { workflow }), "task.workflow").workflow,
      null,
    );
  });
  it("applies replayed deltas once and isolates tasks", () => {
    const first = reduce(initial("a"), event(1), "assistant.delta");
    assert.equal(first.text, "hello");
    assert.equal(reduce(first, event(1), "assistant.delta"), first);
    assert.equal(
      reduce(first, { ...event(2), task_id: "b" }, "assistant.delta"),
      first,
    );
  });
  it("clears old text on revision and ignores stale generation text", () => {
    let state = reduce(initial("a"), event(1), "assistant.delta");
    state = reduce(state, event(2, 1, { note_accepted: true }), "task.updated");
    assert.equal(state.text, "");
    state = reduce(state, event(3, 0), "assistant.delta");
    assert.equal(state.text, "");
    assert.equal(state.cursor, 3);
    state = reduce(state, event(4, 1, { text: "new" }), "assistant.delta");
    assert.equal(state.text, "new");
  });
  it("retains tool progress, proposals and terminal state", () => {
    let state = reduce(
      initial("a"),
      event(1, 0, {
        subtask_id: "balance",
        tool: "get_leave_balance",
        status: "completed",
      }),
      "tool.status",
    );
    state = reduce(
      state,
      event(2, 0, { proposal_id: "p" }),
      "proposal.updated",
    );
    state = reduce(
      state,
      event(3, 0, { status: "cancelled" }),
      "task.terminal",
    );
    assert.equal(state.tools.balance.status, "completed");
    assert.deepEqual(state.proposalIds, ["p"]);
    assert.equal(state.status, "cancelled");
  });
});
describe("SSE boundaries", () => {
  it("ignores heartbeats and parses escaped text", () => {
    assert.equal(parseFrame(": heartbeat"), null);
    const data = event(7, 0, { text: "hello\nworld" });
    assert.deepEqual(
      parseFrame(`id: 7\nevent: assistant.delta\ndata: ${JSON.stringify(data)}`)
        ?.event,
      data,
    );
  });
  it("rejects mismatched cursors", () => {
    assert.throws(() =>
      parseFrame(
        `id: 2\nevent: assistant.delta\ndata: ${JSON.stringify(event(1))}`,
      ),
    );
  });
  it("provides distinct actionable permission messages", () => {
    assert.match(friendly(403), /permission/);
    assert.match(friendly(404), /unavailable/);
    assert.match(friendly(401), /sign in/);
    assert.match(friendly(409), /Refresh/);
  });
});
