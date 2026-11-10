# 0012: OpenAI Responses and server-bound leave workflows

The default-provider decision below is superseded by [ADR 0013](0013-gemini-provider.md):
Gemini is now the Docker default; OpenAI remains an explicit supported option.

The live Compose configuration explicitly selects `openai`, default model
`gpt-5.4-mini`. Direct Python defaults to `fake`; tests explicitly inject FakeLLM,
remove the key and block non-mocked OpenAI HTTP egress. There is no failure
fallback. The official asynchronous SDK uses Responses structured output for the
existing closed read-tool plan and Responses text output for composition. No
LangChain, new database tables or migration is needed.

The model proposes typed intents/arguments. Only existing authorized SQL and
filtered MiniLM (384 dimensions)/pgvector tools execute. Tool results and bounded
owner-only conversation history are reauthorized before transmission. Historical
answers whose citations are no longer authorized are withheld. Document content
is explicitly untrusted and never participates in workflow initiation evidence.

An immutable workflow binds task ID, origin task ID and instruction revision.
Model intent alone cannot open a booking form: initiation also needs explicit
application/preparation language in authenticated original requests or notes.
Continuation requires an existing unresolved workflow in the same owned
conversation and a clear continuation message. The conservative evidence check
currently recognizes English initiation phrases; unsupported phrasing should
clarify. Read-only questions, tutorials, hypotheticals and ambiguous messages
cannot acquire a workflow merely through completion. Confirmation/cancellation
intents direct users to buttons and are not executable model tools.
Live replanning applies deterministic foreign-target refusals to original text
and appended user notes; a note cannot bypass target checks by preserving an
innocent original request. Such mixed foreign-target revisions are conservatively
refused for affected read tools.

The human proposal endpoint requires this server-persisted workflow. Existing
locking, date/balance/ownership/expiry/version checks and atomic exactly-once
confirmation remain authoritative. Pre-upgrade completed tasks without workflow
metadata cannot prepare a new proposal; start an explicit new request instead.
Existing pending proposals retain their confirmation path.

Snapshots project current proposal status rather than trusting replayed workflow
events. The UI additionally checks selected task/revision, hides resolved forms,
and retains edited date drafts per task for the current sign-in. SSE emits a
typed, revision-bound workflow checkpoint; reducers ignore duplicates and older
generations. Final answer chunks still follow composition, not provider token
streaming. Original requests and append-only notes are preserved.

Provider calls have SDK retries (default two), per-attempt timeout (30 seconds),
an overall deadline, 2,048 output tokens, 24,000 input characters and twelve
logical calls per task across checkpoints/revisions. Retries may add network
attempts; usage counts logical calls, successful reported tokens, not billing.
Oldest history is discarded first; oversize current context fails explicitly.
`store=False` disables Responses storage, but authorized data still goes to the
configured OpenAI service. Transport/error details and credentials are never
returned; the UI displays stable actionable error codes. API URL is pinned to
OpenAI, preventing accidental environment-based credential redirection.

References: [official model](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses),
[Python Responses API](https://developers.openai.com/api/reference/python/resources/responses).

Tradeoffs: model planning can fail or misclassify a read; permission enforcement
does not depend on that classification. The English workflow gate deliberately
prefers clarification to accidental action. This remains a demo with in-memory
login sessions, bounded conversation context and no live token transport.
