# AI Usage

## Tool used

OpenAI Codex was used as a coding and review assistant for this POC. The candidate supplied the assignment, selected the main technology stack, proposed the HLD, concurrency approach, policy-change behavior, database relationships, policy precedence, and API contract. Codex reviewed those decisions and implemented the backend with the candidate's direction.

## Codex contributions

Codex contributed the following work:

- Read the assignment and identified requirements concerning authorization, indirect prompt injection, sensitive-data exfiltration, approvals, idempotency, policy versioning, audit replay, budgets, worker failure, deterministic mocking, and frontend demonstrability.
- Reviewed the proposed FastAPI, SQLAlchemy, PostgreSQL, React, worker, and Docker architecture and explained the external-side-effect crash window and the distinction between database delivery and idempotent tool execution.
- Reviewed the ERD and suggested the stable `POLICIES` parent, mutable `USAGE_BUCKETS`, execution-attempt history, approval-to-decision binding, and using structured `AUDIT_EVENTS` for policy-evaluation history.
- Reviewed the candidate's API contract, identified missing observability endpoints for demo identities, budgets, policies, jobs, and execution attempts, and preserved the reviewed contract in `docs/API_CONTRACT.md`.
- Implemented the FastAPI controllers, Pydantic contracts, SQLAlchemy models, authentication and role checks, tool permissions, closed JSON Schema validation, deterministic policy engine, approval workflow, replay flow, registry endpoints, dashboard, budgets, mock provider, and mock tools.
- Implemented the PostgreSQL-backed worker with short job leases, `SELECT FOR UPDATE SKIP LOCKED`, retry records, policy re-evaluation before execution, and idempotent mock message delivery.
- Added seed data for users, agents, tools, permissions, policies, mock documents, and customers.
- Created the Docker and Compose configuration and the executable Postman collection.
- Implemented the React/Vite frontend for the POC, including the gateway overview, agent playground, approval review queue, agent and tool registries, policy version management, audit explorer, policy replay, and request/token budget controls.
- Added the frontend API client, demo identity switcher, redacted review views, lifecycle and approval actions, responsive styling, Nginx static serving, and the Compose `frontend` service on port 3000.
- Smoke-tested every frontend route against the running FastAPI/PostgreSQL stack and fixed route-unmount handling so API-loading effects do not leave stale Promise cleanups in React.
- Wrote automated tests for policy precedence and default deny, authentication, authorization, lifecycle controls, key rotation, user impersonation, malformed calls, idempotency, prompt injection, sensitive-data transfer, approval rejection and expiry, execution deduplication, retries, lease recovery, stale workers, policy changes, simulation and replay isolation, budgets, and PostgreSQL race behavior.
- Expanded the suite to 38 tests and ran all of them against PostgreSQL. The added concurrency coverage exposed and fixed a simultaneous idempotency-key race; worker recovery was also updated to close expired attempts and record the lease loss in the audit trail.
- Wrote the README, architecture notes, POC assumptions, security limitations, setup steps, and test instructions.

## Human review and submission

All generated architecture, code, tests, policy rules, documentation, and security assumptions should be reviewed by the candidate before submission. The complete Codex conversation and available tool-call history must accompany the source code; a summary alone does not meet the assignment requirement.

Before submission, review exported logs and redact only actual secret values such as private credentials or tokens. The fixed credentials in this repository are local demonstration seed values and are not production secrets.
