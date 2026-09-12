# Disseqt AI Security Governance Gateway

A working backend POC for governing AI-agent tool calls. The gateway treats model output and retrieved content as untrusted, authenticates the calling agent, validates tool arguments, checks explicit permissions, applies deterministic versioned policy, coordinates human approval, executes allowlisted mock tools through a durable PostgreSQL job, and records an append-oriented audit trail.

## Run the application

Requirements: Docker Desktop with Docker Compose.

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`, with interactive OpenAPI documentation at `http://localhost:8000/docs`. PostgreSQL data is stored in the `gateway_db` Docker volume and survives container restarts.

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

## Architecture

This is a modular MVC-style monolith with one separately launched worker that reuses the same model and service code:

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

`app/contracts.py` defines request and response-facing validation models. Controllers handle HTTP concerns; service modules implement gateway decisions; SQLAlchemy models own persistence. Components remain modules in one codebase to keep the POC easy to understand and run.

The worker uses `SELECT ... FOR UPDATE SKIP LOCKED`, commits a short lease before execution, and records each attempt. Directly allowed and human-approved requests enter the same execution path. The mock message adapter stores the request ID as a unique idempotency key, so retrying a job cannot create a second message.

For a real external tool, the adapter must pass the stable request ID to an idempotency-aware provider. If the provider cannot offer idempotency or reconciliation, a crash after the external side effect and before its receipt is recorded must end as `OUTCOME_UNKNOWN`, not an unsafe automatic retry.

## Deterministic policy semantics

Published policy versions are immutable. Policy rules are validated and stored as JSON in their version. Evaluation works as follows:

1. Evaluate all rules against gateway-derived facts.
2. Choose the highest matching numeric priority.
3. Resolve effects tied at that priority as `DENY > REQUIRE_APPROVAL > ALLOW`.
4. Return `DENY` when no rule matches.

The audit event stores the policy version, matched winning-tier rule IDs, winning priority, decision, reason code, evaluated facts, and request digest. If policy changes before a worker claims a job, the worker re-evaluates the immutable request facts. A new `REQUIRE_APPROVAL` decision invalidates the old approval and creates a fresh one.

Simulation never creates an action request. Replay records a `POLICY_REPLAYED` audit event and cannot create or release an execution job.

## Security boundaries and assumptions

- Tool names resolve only to registered, active, allowlisted Python adapters. Model output never selects arbitrary Python, URLs, or shell commands.
- Every tool has a closed JSON Schema with `additionalProperties: false`.
- Agent-provided classification labels are ignored. A trusted classification can come from a server-side lookup of a seeded document artifact.
- For this POC, an agent may act only for its registered owner. A production delegation table or identity claim can broaden that relationship explicitly.
- Prompt-injection findings contribute facts to policy but cannot grant permissions or override a denial.
- Sensitive payload and destination checks use deterministic POC inspection. A production system would use organization-owned classification and DLP services.
- Human identity uses a demo header. Agent API keys are SHA-256 digests at rest; newly generated keys are shown once.
- Audit details are append-oriented through the application and redact common content-bearing fields. Production immutability would also use a restricted database role or append-only audit sink.
- Database setup uses SQLAlchemy metadata creation to keep the demo compact. Production evolution should use Alembic migrations.

## API contract review

The supplied contract covered the core gateway, approvals, registries, versioned policy, audit, replay, dashboard, and mock-state workflows. The implementation adds these small endpoints needed to make stated requirements observable:

- `GET /api/v1/users` exposes seeded demo identities and roles.
- `GET /api/v1/policies` exposes the stable policy parent added to the ERD.
- `GET` and `PUT /api/v1/budgets` make usage enforcement inspectable and configurable.
- `GET /api/v1/execution-jobs` and `GET /api/v1/execution-jobs/{request_id}/attempts` expose durable execution and recovery evidence.

No supplied endpoint is redundant. Dedicated activate/deactivate actions keep lifecycle changes auditable and prevent a broad `PATCH` from silently changing active state. Policy simulation and request replay look similar but serve different inputs: simulation evaluates hypothetical facts, while replay uses a historical request snapshot.

Potential frontend additions can wait until the UI contract is designed: paginated request listing and a dedicated worker-recovery action for demonstrations. Neither is necessary to exercise the backend workflows through the current Postman collection.

## Tests

Run the local suite:

```bash
python3 -m pytest -q
```

The suite covers policy priority and effect precedence, authentication/authorization, malformed arguments, idempotency, approval resolution, budget enforcement, untrusted classification, sensitive-data exfiltration, worker duplicate prevention, policy changes before execution, and replay isolation.

PostgreSQL provides the production POC's row-lock semantics. SQLite is used only as a fast local test database; it does not emulate PostgreSQL row-level locking. Approval and idempotency race demonstrations should therefore be run against the Compose environment.

To run every test, including the two real row-lock races, create an isolated test database once and execute the suite in the API image:

```bash
docker compose exec db createdb -U gateway gateway_test
docker compose run --rm \
  -e TEST_DATABASE_URL=postgresql+psycopg://gateway:gateway_demo_only@db:5432/gateway_test \
  api python -m pytest -q
```

The test fixture recreates every table in `gateway_test`, so never point `TEST_DATABASE_URL` at a database containing data.

## AI usage

See [AI_USAGE.md](AI_USAGE.md). Complete assistant conversation logs must be exported and included separately with the submission, with only secret values redacted.
