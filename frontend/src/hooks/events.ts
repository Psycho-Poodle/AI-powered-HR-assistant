import type { Status } from "../api/client";
export interface Event {
  task_id: string;
  seq: number;
  revision: number;
  payload: Record<string, unknown>;
}
export interface StreamState {
  taskId: string;
  cursor: number;
  revision: number;
  text: string;
  status: Status;
  tools: Record<string, { tool: string; status: string }>;
  proposalIds: string[];
}
export function initial(taskId: string): StreamState {
  return {
    taskId,
    cursor: 0,
    revision: 0,
    text: "",
    status: "queued",
    tools: {},
    proposalIds: [],
  };
}
export function reduce(
  state: StreamState,
  event: Event,
  kind: string,
): StreamState {
  if (
    event.task_id !== state.taskId ||
    !Number.isSafeInteger(event.seq) ||
    event.seq <= state.cursor
  )
    return state;
  let next = { ...state, cursor: event.seq };
  if (event.revision < state.revision) return next;
  if (event.revision > state.revision)
    next = { ...next, revision: event.revision, text: "" };
  const p = event.payload;
  if (kind === "assistant.delta")
    next.text += typeof p.text === "string" ? p.text : "";
  if (kind === "task.status" || kind === "task.terminal")
    next.status = p.status as Status;
  if (kind === "tool.status" && typeof p.subtask_id === "string")
    next.tools = {
      ...next.tools,
      [p.subtask_id]: { tool: String(p.tool), status: String(p.status) },
    };
  if (kind === "proposal.updated" && typeof p.proposal_id === "string")
    next.proposalIds = [...new Set([...next.proposalIds, p.proposal_id])];
  return next;
}
export function parseFrame(
  frame: string,
): { kind: string; event: Event } | null {
  let kind = "",
    id = "",
    data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) kind = line.slice(6).trim();
    if (line.startsWith("id:")) id = line.slice(3).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  const event = JSON.parse(data.join("\n")) as Event;
  if (
    !kind ||
    String(event.seq) !== id ||
    typeof event.task_id !== "string" ||
    !Number.isInteger(event.revision) ||
    !event.payload
  )
    throw new Error("Invalid task event");
  return { kind, event };
}
