# API Contract

Base path: `/api/v1`

## Authentication

- Agent endpoints: `Authorization: Bearer <agent-api-key>`.
- Human/frontend endpoints: `X-Demo-User-Id: <user-id>` for the local demonstration.
- Production evolution: replace the demo header with an OIDC/JWT session without changing service authorization rules.

Every response includes `request_id` or `correlation_id` when one exists.

## Error envelope

```json
{
  "error": {
    "code": "AGENT_TOOL_PERMISSION_MISSING",
    "message": "The agent is not authorized for this tool action.",
    "request_id": "3d451898-a0a1-4df5-8378-0c80117292cf"
  }
}
```

Stable status usage:

- `400`: malformed envelope or schema.
- `401`: invalid agent or user authentication.
- `403`: permission or role failure.
- `404`: unknown registry object.
- `409`: idempotency conflict or already-final state.
- `422`: semantically invalid arguments or policy document.
- `429`: request or token budget exhausted.
- `503`: provider unavailable or required dependency unavailable.

## Gateway endpoints

### `POST /tool-calls`

Headers:

```text
Authorization: Bearer <agent-api-key>
Idempotency-Key: <agent-generated-key>
```

Request:

```json
{
  "user_id": "02e1b211-b751-401c-889f-9bfbc43716f3",
  "model": "mock-secure-v1",
  "tool": "messages.send",
  "arguments": {
    "destination": "partner@example.com",
    "message": "Customer account summary"
  },
  "environment": "PRODUCTION",
  "untrusted_context": [
    {
      "source": "RETRIEVED_DOCUMENT",
      "content": "Document excerpt",
      "classification": "CONFIDENTIAL"
    }
  ]
}
```

`classification` on a context item is trusted only when the source artifact was produced by the gateway's mock document tool. Agent-authored classification claims are ignored.

Decision response:

```json
{
  "request_id": "3d451898-a0a1-4df5-8378-0c80117292cf",
  "decision": "REQUIRE_APPROVAL",
  "status": "PENDING_APPROVAL",
  "reason_code": "CONFIDENTIAL_EXTERNAL_APPROVAL",
  "reason": "Confidential data is being sent to an external destination.",
  "policy": {"version": 3},
  "approval_id": "6b02236c-037e-4a3a-882c-351a70e92de6"
}
```

The same idempotency key and canonical request returns the existing response. The same key with a different canonical request returns `409 IDEMPOTENCY_KEY_REUSED`.

### `GET /requests/{request_id}`

Returns current request state, initial decision, approval summary, execution summary, and a redacted lifecycle timeline.

## Agent playground and deterministic provider

### `POST /agent-runs`

```json
{
  "agent_id": "f49faf45-0165-4c4d-adc2-019d3ea6ecdb",
  "user_id": "02e1b211-b751-401c-889f-9bfbc43716f3",
  "prompt": "Send the customer report to partner@example.com",
  "scenario": "CONFIDENTIAL_EXTERNAL_SEND"
}
```

After human and agent authorization, the endpoint atomically reserves an `LLM_PROVIDER` budget before invoking the deterministic provider. Successful calls reconcile to deterministic actual usage. Provider outages charge input tokens and release the reserved output allowance. The resulting proposal then enters the same validation, authorization, policy, approval, and execution flow as `POST /tool-calls`, including its separate `GATEWAY_ACTION` budget. Supported scenarios include safe search, unauthorized updates, high-risk approval, indirect prompt injection, external sensitive-data transfer, malformed arguments, and provider unavailability.

## Approval endpoints

```text
GET  /approvals
GET  /approvals/{approval_id}
POST /approvals/{approval_id}/approve
POST /approvals/{approval_id}/reject
```

`GET /approvals` supports `status`, `agent_id`, `tool_id`, `before`, `after`, `limit`, and an opaque cursor. Results use `created_at DESC, id DESC`; the cursor encodes both fields for stable keyset pagination when timestamps tie. Resolution accepts `{"note": "..."}`. If another resolver wins, the losing request returns `409 APPROVAL_ALREADY_RESOLVED` with the existing state. Rejection and expiry cancel the associated job, clear its lease and retry schedule, cancel only a running attempt, and retain all execution history.

## Registry endpoints

### Agents

```text
GET    /agents
POST   /agents
GET    /agents/{agent_id}
PATCH  /agents/{agent_id}
POST   /agents/{agent_id}/activate
POST   /agents/{agent_id}/deactivate
PUT    /agents/{agent_id}/permissions
POST   /agents/{agent_id}/rotate-key
```

### Tools

```text
GET    /tools
POST   /tools
GET    /tools/{tool_id}
PATCH  /tools/{tool_id}
POST   /tools/{tool_id}/activate
POST   /tools/{tool_id}/deactivate
```

Tool creation validates JSON Schema and requires an allowlisted `adapter_name`. Tool-call arguments use `Draft202012Validator` with `FormatChecker`, so schema formats such as `email` are enforced.

## Policy endpoints

```text
GET  /policies
GET  /policy-versions
POST /policy-versions
GET  /policy-versions/{version_id}
POST /policy-versions/{version_id}/simulate
POST /policy-versions/{version_id}/activate
```

Creating a policy version validates fields, operators, effects, priorities, stable rule identifiers, and reason codes. Simulation never creates an action request, approval, job, or execution. Activation returns a summary of recent decisions that would differ and appends an activation audit event.

## Audit and replay endpoints

```text
GET  /audit-events
GET  /audit-events/{event_id}
POST /requests/{request_id}/replays
```

Audit filtering supports request, agent, user, tool, event type, decision, risk, policy version, date range, text query, limit, and an opaque cursor. Results use `created_at DESC, id DESC`; the cursor encodes both fields for stable keyset pagination when timestamps tie. The text query matches action request IDs and reason codes. Replay accepts a `target_policy_version_id`, reports the original and replay decisions, appends a replay event, and always returns `execution_performed: false`.

## Usage and execution inspection

These endpoints were added during contract review so concurrency and recovery are directly observable:

```text
GET /users
GET /budgets
PUT /budgets
GET /execution-jobs
GET /execution-jobs/{request_id}/attempts
```

Budget payloads include `scope`, either `LLM_PROVIDER` or `GATEWAY_ACTION`. The default is `GATEWAY_ACTION` for backward-compatible direct tool-call configuration.

## Dashboard and mock state

```text
GET /dashboard/summary
GET /mock/documents
GET /mock/customers
GET /mock/message-outbox
GET /health/live
GET /health/ready
```

The dashboard contains recent decisions, denial count, high-risk count, pending approvals, queue depth, and worker heartbeat status.

## Executable examples

The complete executable request set is maintained in [`postman/DisseqtGateway.postman_collection.json`](../postman/DisseqtGateway.postman_collection.json). FastAPI also publishes the generated OpenAPI contract at `/openapi.json` and interactive documentation at `/docs`.
