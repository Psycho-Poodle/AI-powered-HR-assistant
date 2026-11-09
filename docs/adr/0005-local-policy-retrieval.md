# ADR 0005: Repeatable local policy indexing and authorized evidence

Date: 2026-11-08
Status: Phase 4 implementation; execution results recorded in README.

## Local embedding identity and token budget

Use CPU Sentence Transformers `sentence-transformers/all-MiniLM-L6-v2`, pinned
to repository revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
The model supplies normalized 384-dimensional vectors, not hashes or stubs.
An explicit preparation command downloads only the safetensors model, tokenizer
and configuration files. A local manifest records file SHA-256 hashes. Runtime
checks identity/checksums and loads only local files with remote code disabled.
Missing/corrupt assets fail explicitly, without a remote fallback. The model
path is operator-controlled, not a client input. The Docker image caches assets
at build time and sets offline environment flags at runtime.

Use NFC-normalized plain Markdown with HTML tags, script/style contents, link
targets and control characters removed. Poison instructions remain source data;
sanitization is not an instruction-classification or authorization mechanism.
The source model has a 256-token input limit. The blueprint's initial 400-token
chunk suggestion would truncate content, so use 200 content tokens with 60-token
overlap, counted by the real tokenizer. Oversized embedding inputs are rejected
instead of silently truncated. Source size is capped at 1 MiB.

## Transactional ingestion and provenance

HR-only JSON Markdown ingestion derives company from authenticated ActorContext.
It accepts a Markdown basename, source text, slug/version and visibility metadata;
cross-company recipients and extra authority fields are rejected. This is a
bounded Markdown-only API, not the optional multipart ingestion UI or PDF pipeline.
Uploads must be visibly fictional; assignment provenance is reserved for the
controlled seed loader. Raw UTF-8 content hashes remain separate from normalized
chunk text. Source filenames, ACLs, versions, provenance and ingestion/publication
timestamps remain in the policy row.

Migration `0003_rag_provenance` records indexed model/revision/chunker, source hash,
index fingerprint and indexing timestamp on each policy. Existing rows start
unindexed; no old vectors are falsely labeled as having a known model identity.
An advisory lock serializes versions of a tenant/slug. Identical published input
is a no-op, preserving chunk IDs and timestamps; same-version content/ACL changes
conflict. New versions must increase and retire prior published versions only
after successful indexing. Draft, embeddings, chunks and publication share a
transaction/savepoint; failure does not leave partial published content.
The trusted CLI can index existing published policies across companies; this
administrative function is never exposed as an HTTP endpoint or model tool.

## Retrieval and model-context boundary

Exact pgvector cosine SQL ranks a materialized set of chunks filtered by server
tenant, published status, allowed visibility, and current model/chunker/source
identity. Parent and chunk tenant IDs must agree. Similarity is a relevance
heuristic (default minimum 0.2), never an authorization control. Exact scanning
is appropriate for this small corpus; approximate indexes and threshold calibration
remain deferred.

Before evidence leaves retrieval, a second scoped policy query rechecks access
and index identity under shared policy locks. Stable citations bind policy UUID,
version and chunk number, along with source hash/filename and model revision.
The policy tool accepts a server actor and query, not arbitrary SQL, company
selectors or tool names. Its output contains typed citations and explicitly
untrusted document data. A future LLM adapter can consume its JSON context, but
no LLM call, tool dispatcher or generic agent orchestration exists in Phase 4.

The poisoned Summit policy may enter permitted context as untrusted data. It
cannot request a different tenant or grant salary-document permission. Tests
capture the exact future-LLM payload and assert forbidden canary text/IDs are
absent, even when the forbidden document is the nearest unfiltered vector.
This proves the retrieval/context boundary; it does not claim an arbitrary LLM
will always reason correctly over poisoned text.

## Scope

Add authenticated policy search and HR Markdown ingestion, the local indexing CLI,
real inference/vector tests and the test-only model-input recorder. Preserve the
Phase 3 authentication and self-record rules. Do not implement leave tools,
planning, task execution, streaming or UI. Persistent dev/test data is unchanged
by disposable-database verification. Phase 5 requires separate authorization.

References: [SentenceTransformer loading options](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
and [model repository metadata](https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2).
