export interface Session {
  user: { id: string; username: string };
  company: { id: string; slug: string; name: string };
  role: string;
  csrf_token: string;
}
export type Status =
  | "queued"
  | "running"
  | "cancelling"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled";
export interface Source {
  text: string;
  citation: {
    reference: string;
    title: string;
    provenance: string;
    policy_id: string;
    source_filename: string;
  };
}
export interface Result {
  id: string;
  tool: string;
  status: string;
  error?: string | null;
  data?: {
    sources?: Source[];
    days_left?: string;
    valid?: boolean;
    days?: string;
    errors?: string[];
  };
}
export interface Execution {
  answer: string;
  revision: number;
  subtasks: Result[];
  error?: string;
  plan?: {
    steps: { tool: string; args: { start_date?: string; end_date?: string } }[];
  };
}
export interface Task {
  id: string;
  original_request: string;
  status: Status;
  instruction_revision: number;
  instructions: { revision: number; instruction: string }[];
  plan: { execution?: Execution };
}
export interface Proposal {
  id: string;
  task_id: string;
  status: "pending" | "confirmed" | "cancelled" | "expired";
  version: number;
  start_date: string;
  end_date: string;
  days: string;
  expires_at: string;
  calendar: string;
}
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
export function friendly(status: number): string {
  return (
    (
      {
        401: "Your session ended. Please sign in again.",
        403: "You do not have permission for this action.",
        404: "This item is unavailable in your workspace.",
        409: "This item changed. Refresh it before trying again.",
        422: "Check your input and try again.",
      } as Record<number, string>
    )[status] ||
    "The service could not complete this request. Please try again."
  );
}
export async function request<T>(
  path: string,
  csrf?: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    credentials: "same-origin",
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok)
    throw new ApiError(response.status, friendly(response.status));
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>);
}
export const active = (status: Status) =>
  ["queued", "running", "cancelling", "awaiting_confirmation"].includes(status);
