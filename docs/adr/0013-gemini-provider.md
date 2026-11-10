# 0013: Gemini default with explicit OpenAI selection

Google Gemini is the Docker and local dotenv default after OpenAI API credit
exhaustion. OpenAI remains supported; FakeLLM remains the explicit offline/test
provider. Direct Python's safe default is still fake unless configured through
environment variables. Existing database data/schema/migrations are unaffected.

Default Gemini model: `gemini-3.6-flash`, listed as stable and available for
production in Google's catalog at implementation time. Flash suits short typed
HR plans and conversational answers. `GEMINI_MODEL` allows an explicit model
change; access/quota is project-specific, and no free-tier availability is assumed.

The official `google-genai` SDK uses async `generate_content` with native
`response_json_schema`, followed by local Pydantic/DAG validation. The SDK's
`response_schema` translation emitted an unsupported `additional_properties`
field in an initial real test; native JSON Schema resolved that rejection.
Live verification succeeded for a greeting plan and answer. The shared strict
contract, prompts and bounded context live in `agent/live_llm.py`; the OpenAI
adapter retains its official Responses API implementation.

Gemini has no registered mutation tools, automatic SDK function calling is
disabled, and unexpected function-call outputs are rejected. Both providers use
the same server-derived actor, reauthorized result/history context, typed read
registry, workflow evidence checks, SQL permissions and human confirmation path.
Provider failure never dispatches writes or silently changes providers.

The endpoint is pinned to Google's Developer API; explicit backend selection
prevents environment-driven enterprise routing. Credentials are server-only
SecretStr settings. Gemini has configurable per-attempt timeout (30s), at most
two retries by default, SDK retries disabled to avoid multiplying attempts,
4,096 output tokens with low thinking, and shared input/logical-call budgets.
Reported output usage includes thought tokens; logical calls exclude retry
attempts. Provider error details/keys are not returned to the browser or task log.
Rate/quota errors direct users to the selected provider's limits/billing.

The UI exposes provider/model metadata, never keys. `.env.example`, Compose,
runtime metadata, the optional live smoke and test secret stripping support both
providers. Test-only FakeLLM injection and HTTP transport guards prevent external
LLM requests; official SDK tests use mock HTTP. Local MiniLM and pgvector stay real.

Sources: [model](https://aistudio.google.com/docs/models/gemini-3.6-flash),
[official Python SDK](https://googleapis.github.io/python-genai/),
[structured output](https://aistudio.google.com/docs/structured-output).
