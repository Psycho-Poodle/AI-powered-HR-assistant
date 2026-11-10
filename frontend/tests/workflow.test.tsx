import { describe, it } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  LeaveRequestForm,
  canPrepareLeave,
} from "../src/components/LeaveRequestForm.tsx";
import type { Task } from "../src/api/client.ts";

const base: Task = {
  id: "a",
  original_request: "my balance",
  status: "completed",
  instruction_revision: 0,
  instructions: [],
  plan: {},
};
const initiated: Task = {
  ...base,
  original_request: "prepare a leave request",
  workflow: {
    kind: "leave_request",
    task_id: "a",
    origin_task_id: "a",
    revision: 0,
    status: "collecting_dates",
  },
};
const markup = (task: Task, selected = "a") =>
  renderToStaticMarkup(
    <LeaveRequestForm
      task={task}
      selectedTaskId={selected}
      draft={{ start: "2027-01-04", end: "2027-01-06" }}
      onChange={() => {}}
      onSubmit={() => {}}
      busy={false}
    />,
  );
describe("real leave form component", () => {
  it("renders nothing for completed greeting, policy or balance tasks", () => {
    for (const original_request of [
      "hello",
      "late policy",
      "my balance",
      "how do I apply for leave",
    ])
      assert.equal(markup({ ...base, original_request }), "");
  });
  it("renders dates only for the current initiated workflow", () => {
    assert.match(markup(initiated), /Prepare proposal/);
    assert.match(markup(initiated), /2027-01-04/);
  });
  it("rejects stale task IDs, revisions and terminal proposals", () => {
    assert.equal(markup(initiated, "b"), "");
    assert.equal(markup({ ...initiated, instruction_revision: 1 }), "");
    for (const status of [
      "proposed",
      "confirmed",
      "cancelled",
      "expired",
    ] as const)
      assert.equal(
        markup({ ...initiated, workflow: { ...initiated.workflow!, status } }),
        "",
      );
  });
  it("cannot open from completion alone or while running", () => {
    assert.equal(canPrepareLeave(base, "a"), false);
    assert.equal(markup({ ...initiated, status: "running" }), "");
  });
});
