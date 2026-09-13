# Disseqt AI Security Governance Gateway

A working POC for governing AI-agent tool calls. The gateway treats model output and retrieved content as untrusted, authenticates the calling agent, validates tool arguments, checks explicit permissions, applies deterministic versioned policy, coordinates human approval, executes allowlisted mock tools through a durable PostgreSQL job, and records an append-oriented audit trail.

[Watch the video demo](https://youtu.be/0pvEHSkUwVw).

## Run the application

Requirements: Docker Desktop with Docker Compose.

```bash
docker compose up --build
```

The frontend is available at `http://localhost:3000`, the API at `http://localhost:8000`, and interactive OpenAPI documentation at `http://localhost:8000/docs`. PostgreSQL data is stored in the `gateway_db` Docker volume and survives container restarts. Open the frontend over HTTP; a direct `file://` URL does not run the Vite React module graph.

Import [the Postman collection](postman/DisseqtGateway.postman_collection.json) and run its folders in numeric order. The collection contains the seeded local credentials and captures request, approval, and policy-version IDs as it runs.

These values are deliberately fixed local-demo credentials:

| Identity | Value |
|---|---|
| Admin user | `00000000-0000-0000-0000-000000000001` |
| Reviewer user | `00000000-0000-0000-0000-000000000002` |
| Full-access agent key | `ag_demo_full_access_local_only` |
| Limited agent key | `ag_demo_limited_local_only` |

Human endpoints use `X-Demo-User-Id`. Agent endpoints use `Authorization: Bearer <agent-key>`. This is an explicit POC boundary; an OIDC/JWT session can replace the human header without changing service authorization.

To reset all demonstration data:

```bash
docker compose down -v
docker compose up --build
```

The current schema separates provider and gateway-action budget buckets. If upgrading an older local checkout that already has a `gateway_db` volume, run the reset command once because this compact POC uses metadata creation rather than migrations.

## Architecture

This is a modular MVC-style monolith with one separately launched worker and a static React frontend:

```text
React/Postman/Agent
        |
FastAPI controllers        app/controllers/
        |
Domain services            app/core.py, app/policy.py, app/security.py
        |
SQLAlchemy models          app/models.py
        |
PostgreSQL  <----------  Python worker (app/worker.py)
                              |
                        allowlisted mock adapters
```

The frontend is a Vite React application in `frontend/`. Its pages cover the dashboard, deterministic agent playground, approvals, agent and tool registries, policy versions, audit explorer, replay, and usage controls. The production container serves the built SPA with Nginx and proxies `/api` to FastAPI.

`app/contracts.py` defines request and response-facing validation models. Controllers handle HTTP concerns; service modules implement gateway decisions; SQLAlchemy models own persistence. Components remain modules in one codebase to keep the POC easy to understand and run.

The worker uses `SELECT ... FOR UPDATE SKIP LOCKED`, commits a short lease before execution, and records each attempt. Directly allowed and human-approved requests enter the same execution path. Immediately before calling an adapter, the worker locks and rechecks the agent, user, tool, ownership, and agent-tool permission. Revoked authorization cancels the attempt without performing the side effect. The mock message adapter stores the request ID as a unique idempotency key, so retrying a job cannot create a second message.

Each worker tick also expires overdue approvals. Rejected or expired approvals mark any associated job `CANCELLED`, clear its lease and retry schedule, and retain all prior execution attempts. A currently running attempt is cancelled; completed, failed, and lease-expired attempts remain unchanged.

For a real external tool, the adapter must pass the stable request ID to an idempotency-aware provider. If the provider cannot offer idempotency or reconciliation, a crash after the external side effect and before its receipt is recorded must end as `OUTCOME_UNKNOWN`, not an unsafe automatic retry.

## Deterministic policy semantics

Published policy versions are immutable. Policy rules are validated and stored as JSON in their version. Evaluation works as follows:

1. Evaluate all rules against gateway-derived facts.
2. Choose the highest matching numeric priority.
3. Resolve effects tied at that priority as `DENY > REQUIRE_APPROVAL > ALLOW`.
4. Return `DENY` when no rule matches.

The audit event stores the policy version, matched winning-tier rule IDs, winning priority, decision, reason code, evaluated facts, and request digest. If policy changes before a worker claims a job, the worker re-evaluates the immutable request facts. A new `REQUIRE_APPROVAL` decision invalidates the old approval and creates a fresh one.

The seeded policy explicitly denies external actions influenced by detected prompt injection at priority 95. This makes the security finding change the policy outcome independently of sensitive-content detection.

Simulation never creates an action request. Replay records a `POLICY_REPLAYED` audit event and cannot create or release an execution job.

## Security boundaries and assumptions

- Tool names resolve only to registered, active, allowlisted Python adapters. Model output never selects arbitrary Python, URLs, or shell commands.
- Every tool has a closed JSON Schema with `additionalProperties: false`; validation uses the Draft 2020-12 format checker, including the seeded email format.
- Agent-provided classification labels are ignored. A trusted classification can come from a server-side lookup of a seeded document artifact.
- For this POC, an agent may act only for its registered owner. A production delegation table or identity claim can broaden that relationship explicitly.
- Prompt-injection findings contribute facts to policy but cannot grant permissions or override a denial.
- Sensitive payload and destination checks use deterministic POC inspection. A production system would use organization-owned classification and DLP services.
- Human identity uses a demo header. Agent API keys are SHA-256 digests at rest; newly generated keys are shown once.
- Audit details are append-oriented through the application and redact common content-bearing fields. Production immutability would also use a restricted database role or append-only audit sink.
- Database setup uses SQLAlchemy metadata creation to keep the demo compact. Production evolution should use Alembic migrations.

## Usage accounting

Budgets have two explicit scopes. `LLM_PROVIDER` is reserved before `/agent-runs` invokes the deterministic provider. A successful call releases unused reserved output tokens and charges deterministic actual usage. A provider outage charges the input tokens and releases the output allowance. `GATEWAY_ACTION` is charged when an already-produced proposal enters `/tool-calls`; `/agent-runs` also passes its provider result through that same action budget.

Fresh installations seed a coherent security story for the dashboard and audit explorer: successful execution, sensitive-data and prompt-injection denials, pending and rejected approvals, authorization failure, provider outage, and a side-effect-free replay.

## API contract review

The supplied contract covered the core gateway, approvals, registries, versioned policy, audit, replay, dashboard, and mock-state workflows. The implementation adds these small endpoints needed to make stated requirements observable:

- `GET /api/v1/users` exposes seeded demo identities and roles.
- `GET /api/v1/policies` exposes the stable policy parent added to the ERD.
- `GET` and `PUT /api/v1/budgets` make usage enforcement inspectable and configurable.
- `GET /api/v1/execution-jobs` and `GET /api/v1/execution-jobs/{request_id}/attempts` expose durable execution and recovery evidence.

No supplied endpoint is redundant. Dedicated activate/deactivate actions keep lifecycle changes auditable and prevent a broad `PATCH` from silently changing active state. Policy simulation and request replay look similar but serve different inputs: simulation evaluates hypothetical facts, while replay uses a historical request snapshot.

The frontend exposes the same workflows visually: scenario execution, pending approval review, agent and tool lifecycle, policy version activation, audit filtering, replay, and budget inspection. Action IDs are displayed in full and the audit explorer searches by action ID or reason code. A paginated request listing and a dedicated worker-recovery action remain optional enhancements for a larger production console; they are not required to exercise the POC through the current UI or Postman collection.

## Tests

The candidate-run manual scenarios and their observed outcomes are recorded in [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md). All three end-to-end validation groups passed: policy behavior and version changes; concurrency, retries, and budgets; and AI security with replay isolation.

Run the local suite:

```bash
python3 -m pytest -q
```

The suite covers policy priority and effect precedence, default deny, authentication and authorization, agent and tool lifecycle, key rotation, JSON Schema formats, idempotency, approval expiry and resolution, execution-history preservation, stable keyset pagination, scoped budget enforcement, provider reservation and failure accounting, seeded records, untrusted classification, prompt injection, sensitive-data exfiltration, simulation and replay isolation, worker retries and lease recovery, stale-worker fencing, permission revocation before execution, and policy changes before execution.

PostgreSQL provides the production POC's row-lock semantics. SQLite is used only as a fast local test database; it does not emulate PostgreSQL row-level locking. Approval and idempotency race demonstrations should therefore be run against the Compose environment.

To run every test, including the PostgreSQL row-lock races, create an isolated test database once and execute the suite in the API image:

```bash
docker compose exec db createdb -U gateway gateway_test
docker compose run --rm \
  -e TEST_DATABASE_URL=postgresql+psycopg://gateway:gateway_demo_only@db:5432/gateway_test \
  api python -m pytest -q
```

The test fixture recreates every table in `gateway_test`, so never point `TEST_DATABASE_URL` at a database containing data.

The complete suite currently contains 50 tests. Six PostgreSQL-only tests exercise concurrent approval resolution, duplicate approval, atomic budget exhaustion, identical and conflicting idempotency-key races, and competing worker claims.

## AI usage

See [AI_USAGE.md](AI_USAGE.md). Complete assistant conversation logs must be exported and included separately with the submission, with only secret values redacted.
