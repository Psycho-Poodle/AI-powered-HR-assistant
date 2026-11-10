import { useEffect, useRef, useState } from "react";
import {
  active,
  ApiError,
  request,
  type Proposal,
  type Session,
  type Task,
  type Runtime,
} from "../api/client";
import {
  LeaveRequestForm,
  type DateDraft,
} from "../components/LeaveRequestForm";
import { useTaskStream } from "../hooks/useTaskStream";

const names: Record<string, string> = {
  get_leave_balance: "Leave balance",
  get_employee_profile: "Employee profile",
  get_leave_history: "Leave history",
  search_hr_policy: "Policy search",
  validate_leave_request: "Leave validation",
  clarify: "Clarification",
  talk: "Response",
  refuse: "Access boundary",
};
interface Chat {
  id: string;
  title: string;
  tasks: string[];
}

export function App() {
  const [session, setSession] = useState<Session | null>(null),
    [username, setUsername] = useState("maya"),
    [password, setPassword] = useState("");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [chats, setChats] = useState<Chat[]>([]),
    [chatId, setChatId] = useState<string | null>(null);
  const [task, setTask] = useState<Task | null>(null),
    [selected, setSelected] = useState<string | null>(null),
    [draft, setDraft] = useState("");
  const [proposals, setProposals] = useState<Record<string, Proposal>>({}),
    [dateDrafts, setDateDrafts] = useState<Record<string, DateDraft>>({}),
    [runtime, setRuntime] = useState<Runtime | null>(null),
    [booking, setBooking] = useState("");
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const refreshCounter = useRef(0);
  function failure(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) {
      reset();
      setSession(null);
    }
    if (cause instanceof ApiError && [403, 404].includes(cause.status)) {
      setTask(null);
      setSelected(null);
    }
    setError(
      cause instanceof Error
        ? cause.message
        : "Something went wrong. Please try again.",
    );
  }
  function reset() {
    setChats([]);
    setChatId(null);
    setSelected(null);
    setTask(null);
    setDraft("");
    setProposals({});
    setBooking("");
    setDateDrafts({});
    setRuntime(null);
  }
  async function refresh() {
    const id = selectedRef.current,
      identity = sessionRef.current;
    if (!id || !identity) return;
    const version = ++refreshCounter.current;
    try {
      const next = await request<Task>(`/tasks/${id}`);
      if (
        selectedRef.current !== id ||
        sessionRef.current !== identity ||
        version !== refreshCounter.current
      )
        return;
      setTask(next);
      if (next.proposals)
        setProposals((old) => ({
          ...old,
          ...Object.fromEntries(next.proposals!.map((p) => [p.id, p])),
        }));
      const dates = next.workflow;
      setDateDrafts((old) =>
        old[id]?.edited
          ? old
          : {
              ...old,
              [id]: {
                start: dates?.start_date || old[id]?.start || "",
                end: dates?.end_date || old[id]?.end || "",
              },
            },
      );
    } catch (cause) {
      if (selectedRef.current === id && sessionRef.current === identity)
        failure(cause);
    }
  }
  const { state, connection } = useTaskStream(
    selected,
    () => void refresh(),
    failure,
  );
  useEffect(() => {
    setTask(null);

    setBooking("");
    void refresh();
  }, [selected]);
  useEffect(() => {
    if (state.taskId !== selected || !session) return;
    const identity = session;
    for (const id of state.proposalIds) {
      const taskId = selected;
      void request<Proposal>(`/leave/proposals/${id}`)
        .then((p) => {
          if (selectedRef.current === taskId && sessionRef.current === identity)
            setProposals((old) => ({ ...old, [id]: p }));
        })
        .catch((cause) => {
          if (selectedRef.current === taskId && sessionRef.current === identity)
            failure(cause);
        });
    }
  }, [state.proposalIds]);
  const currentStatus =
    state.taskId !== selected
      ? "queued"
      : task &&
          task.instruction_revision >= state.revision &&
          connection === "complete"
        ? task.status
        : state.status;
  const running = !!selected && active(currentStatus);
  const cancellable = running && currentStatus !== "cancelling";
  const sources =
    task?.plan.execution?.subtasks.flatMap((r) => r.data?.sources || []) || [];
  const answer =
    task?.plan.execution?.answer ||
    (state.revision >= (task?.instruction_revision ?? 0) ? state.text : "");
  const dateDraft = selected
    ? dateDrafts[selected] || { start: "", end: "" }
    : { start: "", end: "" };
  const visibleProposals = Object.values(proposals).filter(
    (p) => p.task_id === selected,
  );
  async function login(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const identity = await request<Session>("/auth/login", undefined, {
        username,
        password,
      });
      reset();
      setSession(identity);
      setPassword("");
      setRuntime(await request<Runtime>("/runtime"));
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "Username or password was not accepted."
          : cause instanceof Error
            ? cause.message
            : "Unable to sign in.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!session || !draft.trim() || busy) return;
    setBusy(true);
    setError("");
    const message = draft;
    try {
      if (running && selected) {
        await request(`/tasks/${selected}/instructions`, session.csrf_token, {
          message,
          expected_revision: task?.instruction_revision ?? state.revision,
          client_note_id: crypto.randomUUID(),
        });
        setDraft("");
        await refresh();
      } else {
        let conversation = chatId;
        if (!conversation) {
          const created = await request<{ id: string }>(
            "/conversations",
            session.csrf_token,
            { title: message.slice(0, 70) },
          );
          conversation = created.id;
          setChatId(conversation);
          setChats((old) => [
            { id: created.id, title: message.slice(0, 70), tasks: [] },
            ...old,
          ]);
        }
        const queued = await request<{ task_id: string }>(
          `/conversations/${conversation}/tasks`,
          session.csrf_token,
          { message },
        );
        setChats((old) =>
          old.map((c) =>
            c.id === conversation
              ? { ...c, tasks: [...c.tasks, queued.task_id] }
              : c,
          ),
        );
        setSelected(queued.task_id);
        setDraft("");
      }
    } catch (cause) {
      failure(cause);
      if (selected) void refresh();
    } finally {
      setBusy(false);
    }
  }
  async function prepare(event: React.FormEvent) {
    event.preventDefault();
    if (!session || !selected) return;
    setBusy(true);
    setError("");
    try {
      const p = await request<Proposal>(
        "/leave/proposals",
        session.csrf_token,
        {
          task_id: selected,
          start_date: dateDraft.start,
          end_date: dateDraft.end,
          leave_type: "annual",
        },
      );
      setProposals((old) => ({ ...old, [p.id]: p }));
    } catch (cause) {
      failure(cause);
    } finally {
      setBusy(false);
    }
  }
  async function act(p: Proposal, action: "confirm" | "cancel") {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      if (action === "confirm") {
        const result = await request<{ remaining_days: string }>(
          `/leave/proposals/${p.id}/confirm`,
          session.csrf_token,
          { expected_version: p.version },
        );
        setBooking(
          `Leave booked. Remaining balance: ${result.remaining_days} days.`,
        );
      } else
        await request(`/leave/proposals/${p.id}/cancel`, session.csrf_token, {
          expected_version: p.version,
        });
      const next = await request<Proposal>(`/leave/proposals/${p.id}`);
      setProposals((old) => ({ ...old, [p.id]: next }));
    } catch (cause) {
      failure(cause);
      try {
        const next = await request<Proposal>(`/leave/proposals/${p.id}`);
        setProposals((old) => ({ ...old, [p.id]: next }));
      } catch {
        /* Keep the original action error. */
      }
    } finally {
      setBusy(false);
    }
  }
  if (!session)
    return (
      <div className="login">
        <div className="login-brand">
          <div className="brand-mark">p</div>
          <span>people / workspace</span>
        </div>
        <main className="login-card">
          <span className="eyebrow">YOUR PEOPLE, YOUR WORKSPACE</span>
          <h1>
            A little less admin.
            <br />A little more clarity.
          </h1>
          <p>
            Policies, leave and everyday HR questions.
            <br />
            One conversation, within your company.
          </p>
          <form onSubmit={login}>
            <label>
              Username
              <input
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button className="primary" disabled={busy}>
              {busy ? "Signing in…" : "Sign in →"}
            </button>
          </form>
          <small>
            Demo accounts: maya · leila · ravi
            <br />
            Use the configured demo password.
          </small>
        </main>
        <div className="login-footer">
          A private workspace for everyday questions.
        </div>
      </div>
    );
  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="wordmark">
          <div className="brand-mark">p</div>
          <b>
            people<span> / workspace</span>
          </b>
        </div>
        <div className="tenant">
          <span className="tenant-icon">
            {session.company.name.slice(0, 1)}
          </span>
          <div>
            <strong>{session.company.name}</strong>
            <small>
              {session.role === "hr" ? "HR workspace" : "Employee workspace"}
            </small>
          </div>
          <span className="online" />
        </div>
        <button
          className="new-chat"
          onClick={() => {
            setChatId(null);
            setSelected(null);
            setTask(null);
            setDraft("");
            setError("");
          }}
        >
          ＋ New conversation <span>↗</span>
        </button>
        <span className="section-label">THIS SESSION</span>
        <nav aria-label="Conversations">
          {chats.length === 0 && (
            <p className="sidebar-empty">
              Your conversations will appear here.
            </p>
          )}
          {chats.map((c) => (
            <div key={c.id}>
              <button
                className={chatId === c.id ? "chat-link selected" : "chat-link"}
                onClick={() => {
                  setChatId(c.id);
                  setSelected(c.tasks.at(-1) || null);
                  setError("");
                }}
              >
                <span>◫</span> {c.title}
              </button>
              {chatId === c.id &&
                c.tasks.length > 1 &&
                c.tasks.map((id, i) => (
                  <button
                    key={id}
                    className="task-link"
                    aria-current={selected === id ? "true" : undefined}
                    onClick={() => setSelected(id)}
                  >
                    Request {i + 1}
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy">
            <span>◇</span>
            <p>
              Company-scoped by design.
              <br />
              Your HR records stay yours.
            </p>
          </div>
          <div className="account">
            <span className="avatar">
              {session.user.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <b>{session.user.username}</b>
              <small>{session.role}</small>
            </div>
            <button
              aria-label="Sign out"
              disabled={busy}
              title="Sign out"
              onClick={async () => {
                try {
                  await request(
                    "/auth/logout",
                    session.csrf_token,
                    undefined,
                    "POST",
                  );
                  reset();
                  setSession(null);
                  setError("");
                } catch (cause) {
                  failure(cause);
                }
              }}
            >
              ↪
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <header>
          <div>
            <span className="eyebrow">PEOPLE ASSISTANT</span>
            <h1>{chatId ? "Conversation" : "Your everyday HR, simplified."}</h1>
          </div>
          <span className="provider-badge" aria-label="LLM provider">
            {task?.plan.execution?.provider || runtime?.provider || "provider"}
            {task?.plan.execution?.model || runtime?.model
              ? ` / ${task?.plan.execution?.model || runtime?.model}`
              : ""}
            {runtime && !runtime.configured ? " / not configured" : ""}
          </span>
          <span className="scope-badge">◇ {session.company.slug} only</span>
        </header>
        <div className="chat-scroll">
          <div className="conversation">
            {error && (
              <div className="error" role="alert">
                {error}
                <button className="text-button" onClick={() => void refresh()}>
                  Refresh
                </button>
              </div>
            )}
            {!selected ? (
              <section className="welcome">
                <span className="welcome-icon">✳</span>
                <span className="eyebrow">A CLEARER WORKDAY</span>
                <h2>
                  What can I help
                  <br />
                  you untangle?
                </h2>
                <p>
                  Check your leave, find a policy, or prepare a request.
                  <br />
                  We’ll take it one step at a time.
                </p>
                <div className="suggestions">
                  {[
                    [
                      "01",
                      "A little time off",
                      "Check my remaining leave balance",
                    ],
                    [
                      "02",
                      "Know where you stand",
                      "Explain the late attendance policy",
                    ],
                    ["03", "Make a plan", "Help me prepare a leave request"],
                  ].map(([n, title, text]) => (
                    <button key={n} onClick={() => setDraft(text)}>
                      <span>{n} ↗</span>
                      <b>{title}</b>
                      <small>{text}</small>
                    </button>
                  ))}
                </div>
              </section>
            ) : (
              <>
                <div className="request">
                  <span className="eyebrow">YOUR ORIGINAL REQUEST</span>
                  <p>{task?.original_request || "Loading request…"}</p>
                  <small>
                    Task <code data-testid="task-id">{selected}</code>
                  </small>
                </div>
                {task?.instructions.map((note) => (
                  <div className="note" key={note.revision}>
                    <span>↳ Note {note.revision}</span>
                    <p>{note.instruction}</p>
                  </div>
                ))}
                <section className="assistant">
                  <div className="assistant-heading">
                    <span className="assistant-mark">✳</span>
                    <strong>People assistant</strong>
                    <span className="status" role="status">
                      {currentStatus} · {connection}
                    </span>
                  </div>
                  <div className="tools" aria-label="Tool activity">
                    {Object.entries(state.tools).map(([id, t]) => (
                      <div key={id}>
                        <span
                          className={t.status === "completed" ? "done" : ""}
                        >
                          {t.status === "completed" ? "✓" : "◌"}
                        </span>
                        <span>{names[t.tool] || t.tool}</span>
                        <small>{t.status}</small>
                      </div>
                    ))}
                  </div>
                  {answer ? (
                    <p className="answer">{answer}</p>
                  ) : (
                    <p className="muted">
                      {currentStatus === "cancelled"
                        ? "This request was cancelled."
                        : currentStatus === "failed"
                          ? "This request could not finish. You can review its results or send a new request."
                          : "Working through your request… You can add a note below."}
                    </p>
                  )}
                  {task?.plan.execution?.error && (
                    <p className="error">
                      {providerError(task.plan.execution.error)}
                    </p>
                  )}
                  {sources.length > 0 && (
                    <div className="sources">
                      <span className="section-label">
                        REFERENCES · UNTRUSTED DOCUMENT TEXT
                      </span>
                      {sources.map((source, i) => (
                        <details key={source.citation.reference + String(i)}>
                          <summary>
                            {source.citation.title}{" "}
                            <span>{source.citation.reference}</span>
                          </summary>
                          <small>
                            {source.citation.source_filename} ·{" "}
                            {source.citation.provenance === "fictional_demo"
                              ? "Fictional demo policy"
                              : "Assignment source"}
                          </small>
                          <p>{source.text}</p>
                        </details>
                      ))}
                    </div>
                  )}
                </section>
                <LeaveRequestForm
                  task={
                    task &&
                    task.instruction_revision >= state.revision &&
                    !visibleProposals.length
                      ? task
                      : null
                  }
                  selectedTaskId={selected}
                  draft={dateDraft}
                  onChange={(value) => {
                    if (selected)
                      setDateDrafts((old) => ({ ...old, [selected]: value }));
                  }}
                  onSubmit={prepare}
                  busy={busy}
                />
                {visibleProposals.map((p) => (
                  <section className="approval proposal" key={p.id}>
                    <span className="eyebrow">
                      {p.status === "pending"
                        ? "YOUR APPROVAL NEEDED"
                        : p.status.toUpperCase()}
                    </span>
                    <h3>{p.days} days of annual leave</h3>
                    <p>
                      {p.start_date} → {p.end_date}
                    </p>
                    <small>
                      Fictional weekday-only calendar · Expires{" "}
                      {new Date(p.expires_at).toLocaleString()}
                    </small>
                    {p.status === "pending" && (
                      <div className="approval-actions">
                        <button
                          className="primary"
                          disabled={
                            busy || Date.parse(p.expires_at) <= Date.now()
                          }
                          onClick={() => void act(p, "confirm")}
                        >
                          Confirm booking
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => void act(p, "cancel")}
                        >
                          Cancel proposal
                        </button>
                      </div>
                    )}
                  </section>
                ))}
                {booking && (
                  <p className="success" role="status">
                    {booking}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
        <footer className="composer-area">
          <form className="composer" onSubmit={send}>
            <label className="sr-only" htmlFor="message">
              {running ? "Add a note to this task" : "Message People assistant"}
            </label>
            <textarea
              id="message"
              placeholder={
                running ? "Add a note to this task…" : "Ask about your workday…"
              }
              value={draft}
              maxLength={4000}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="composer-actions">
              <span>
                {running
                  ? "↳ Notes stay on the same task"
                  : "◇ Private to your workspace"}
              </span>
              <div>
                {cancellable && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={async () => {
                      if (!session || !selected) return;
                      try {
                        await request(
                          `/tasks/${selected}/cancel`,
                          session.csrf_token,
                          undefined,
                          "POST",
                        );
                        await refresh();
                      } catch (cause) {
                        failure(cause);
                      }
                    }}
                  >
                    Stop task
                  </button>
                )}
                <button
                  className="send"
                  disabled={
                    busy || !draft.trim() || currentStatus === "cancelling"
                  }
                  aria-label={running ? "Send note" : "Send message"}
                >
                  ↑
                </button>
              </div>
            </div>
          </form>
          <small className="composer-help">
            {running
              ? "Keep the conversation going. New instructions revise this task."
              : "Answers reference company sources. Booking always needs your confirmation."}{" "}
            <span>Enter to send · Shift + Enter for a new line</span>
          </small>
        </footer>
      </main>
    </div>
  );
}

function providerError(code: string) {
  const errors: Record<string, string> = {
    provider_missing_key:
      "The live AI service is not configured. Ask the administrator to configure its server API key.",
    provider_auth:
      "The AI service rejected its server credentials. Contact the administrator.",
    provider_invalid_request:
      "The AI provider rejected the configured model or request options. Ask the administrator to check the provider configuration.",
    provider_model_access:
      "The configured AI model is not accessible. Ask the administrator to check model access.",
    provider_timeout: "The AI service timed out. Please retry your request.",
    provider_rate_limited:
      "The AI provider reached a rate or quota limit. Check its API quota and billing; for temporary rate limits, wait before retrying.",
    provider_quota_exhausted:
      "OpenAI API credits are exhausted or an API usage limit was reached. Ask the administrator to check API billing and limits. Retrying will not resolve this billing issue.",
    provider_unavailable:
      "The live AI service is unavailable. Your data has not been booked automatically.",
    provider_invalid_response:
      "The AI service returned an invalid response. No action was approved.",
    provider_context_limit:
      "This request is too large. Shorten it or start a new conversation.",
    provider_budget_exceeded:
      "This task reached its AI request limit. Start a new request.",
  };
  return (
    errors[code] ||
    "The response is incomplete or a source is no longer available. Refresh to check current access."
  );
}
