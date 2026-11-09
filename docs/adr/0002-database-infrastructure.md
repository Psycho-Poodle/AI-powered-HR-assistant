# ADR 0002: Separate development and integration-test clusters

Date: 2026-11-07
Status: Accepted and implemented for Phase 1.

Use the version-tagged `pgvector/pgvector:0.8.0-pg16` image for two independent
Compose services. Each has its own named persistent volume, network, database
name and password. The API joins only the development network. Bind configurable
host ports to loopback. Keep local secrets in ignored `.env`; `.env.example`
contains empty password placeholders and Compose rejects missing passwords.
Use URL-safe passwords (for example, random hexadecimal strings) because Compose
interpolates credentials into the API connection URL.

The shared init script installs only `vector`. PostgreSQL executes it only on
an empty data directory. Application tables, migrations, seed data, embeddings,
tenant access rules and RAG remain deferred. Do not delete persistent volumes to
fix configuration; initialization credentials and database names are immutable
for an existing cluster unless changed explicitly inside PostgreSQL.

Use psycopg 3 for a small synchronous connectivity probe rather than adding an
ORM before schema work. Typed environment settings require an explicit PostgreSQL
database URL. API startup fails if connectivity or the extension probe fails.
The public liveness response stays unchanged after startup.

The read-only integration test checks real extension versions, cosine-distance
SQL, different database names/users, and different PostgreSQL system identifiers.
Different system identifiers prove these are independent clusters even if their
host URLs differ. It also requires zero public tables for this phase. Missing
integration URLs cause an explicit skip; configured but unreachable databases
fail. The test needs local cluster-admin access to `pg_control_system()`; these
bootstrap users are not production application roles. Least-privilege roles and
tenant isolation belong to later phases.

Both clusters are persistent so restart testing is possible; tests do not reset
or mutate development data. Unit tests isolate the startup probe; the integration
test and running API exercise actual PostgreSQL. The image is pinned by version
tag rather than immutable digest, and Python dependencies remain bounded ranges.
Phase 2 (application schema and seed) requires separate authorization.
