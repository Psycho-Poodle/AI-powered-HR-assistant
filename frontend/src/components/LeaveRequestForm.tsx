import type { FormEvent } from "react";
import type { Task } from "../api/client";

export interface DateDraft {
  start: string;
  end: string;
  edited?: boolean;
}

export function canPrepareLeave(
  task: Task | null,
  selectedTaskId: string | null,
): boolean {
  const w = task?.workflow;
  return !!(
    task &&
    task.id === selectedTaskId &&
    task.status === "completed" &&
    w &&
    w.kind === "leave_request" &&
    w.task_id === task.id &&
    w.revision === task.instruction_revision &&
    ["collecting_dates", "ready"].includes(w.status)
  );
}

export function LeaveRequestForm({
  task,
  selectedTaskId,
  draft,
  onChange,
  onSubmit,
  busy,
}: {
  task: Task | null;
  selectedTaskId: string | null;
  draft: DateDraft;
  onChange: (draft: DateDraft) => void;
  onSubmit: (event: FormEvent) => void;
  busy: boolean;
}) {
  if (!canPrepareLeave(task, selectedTaskId)) return null;
  return (
    <section className="approval" data-testid="leave-request-form">
      <span className="eyebrow">LEAVE REQUEST</span>
      <h3>Prepare first. Confirm when ready.</h3>
      <p>A proposal does not reserve or deduct leave.</p>
      <form onSubmit={onSubmit} className="dates">
        <label>
          Start date
          <input
            type="date"
            value={draft.start}
            onChange={(e) =>
              onChange({ ...draft, start: e.target.value, edited: true })
            }
            required
          />
        </label>
        <label>
          End date
          <input
            type="date"
            min={draft.start}
            value={draft.end}
            onChange={(e) =>
              onChange({ ...draft, end: e.target.value, edited: true })
            }
            required
          />
        </label>
        <button disabled={busy}>Prepare proposal</button>
      </form>
      <small>
        Fictional demo convention: inclusive weekdays only; no holiday calendar.
      </small>
    </section>
  );
}
