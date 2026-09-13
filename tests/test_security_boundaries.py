from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import ActionRequest, Approval, AuditEvent, ExecutionJob, MockMessage, now
from app.policy import evaluate
from app.worker import tick
from conftest import tool_call


ADMIN_ID = "00000000-0000-0000-0000-000000000001"
VIEWER_HEADERS = {"X-Demo-User-Id": "00000000-0000-0000-0000-000000000003"}
FULL_AGENT_ID = "00000000-0000-0000-0000-000000000010"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000020"


def test_policy_defaults_to_deny_when_nothing_matches():
    result = evaluate([{
        "id": "low-risk-only", "priority": 10, "effect": "ALLOW",
        "reason_code": "LOW_ONLY", "reason": "low only",
        "conditions": [{"field": "risk", "op": "eq", "value": "LOW"}],
    }], {"risk": "HIGH"})
    assert result == {
        "decision": "DENY", "reason_code": "DEFAULT_DENY",
        "reason": "No policy rule allows this action.",
        "winning_priority": None, "matched_rule_ids": [],
    }


def test_agent_authentication_and_idempotency_key_are_required(client, agent_headers):
    missing = client.post("/api/v1/tool-calls", json=tool_call())
    invalid = client.post("/api/v1/tool-calls", headers={"Authorization": "Bearer invalid"}, json=tool_call())
    no_key = client.post("/api/v1/tool-calls", headers=agent_headers, json=tool_call())

    assert (missing.status_code, missing.json()["error"]["code"]) == (401, "AGENT_AUTH_REQUIRED")
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (401, "AGENT_AUTH_INVALID")
    assert (no_key.status_code, no_key.json()["error"]["code"]) == (400, "IDEMPOTENCY_KEY_REQUIRED")
    with SessionLocal() as db:
        codes = {event.reason_code for event in db.scalars(select(AuditEvent)).all()}
        assert {"AGENT_AUTH_REQUIRED", "AGENT_AUTH_INVALID"} <= codes


def test_disabled_agent_tool_and_unapproved_model_are_blocked(client, agent_headers, admin_headers):
    assert client.post(f"/api/v1/agents/{FULL_AGENT_ID}/deactivate", headers=admin_headers).status_code == 200
    disabled_agent = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "disabled-agent"}, json=tool_call())
    assert (disabled_agent.status_code, disabled_agent.json()["error"]["code"]) == (401, "AGENT_AUTH_INVALID")

    assert client.post(f"/api/v1/agents/{FULL_AGENT_ID}/activate", headers=admin_headers).status_code == 200
    wrong_model_body = tool_call()
    wrong_model_body["model"] = "unapproved-model"
    wrong_model = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "wrong-model"}, json=wrong_model_body)
    assert (wrong_model.status_code, wrong_model.json()["error"]["code"]) == (403, "MODEL_NOT_ALLOWED")

    tool = next(item for item in client.get("/api/v1/tools", headers=admin_headers).json() if item["name"] == "documents.search")
    assert client.post(f"/api/v1/tools/{tool['id']}/deactivate", headers=admin_headers).status_code == 200
    disabled_tool = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "disabled-tool"}, json=tool_call())
    assert (disabled_tool.status_code, disabled_tool.json()["error"]["code"]) == (403, "TOOL_DISABLED")


def test_viewer_can_inspect_but_cannot_mutate(client):
    assert client.get("/api/v1/agents", headers=VIEWER_HEADERS).status_code == 200
    forbidden = client.post("/api/v1/agents", headers=VIEWER_HEADERS, json={"name": "viewer-agent", "owner_id": ADMIN_ID})
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "ROLE_FORBIDDEN")


def test_rotating_agent_key_immediately_revokes_old_key(client, agent_headers, admin_headers):
    rotated = client.post(f"/api/v1/agents/{FULL_AGENT_ID}/rotate-key", headers=admin_headers)
    assert rotated.status_code == 200
    old_key = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "old-key"}, json=tool_call())
    new_key = client.post("/api/v1/tool-calls", headers={
        "Authorization": f"Bearer {rotated.json()['api_key']}", "Idempotency-Key": "new-key",
    }, json=tool_call())
    assert (old_key.status_code, old_key.json()["error"]["code"]) == (401, "AGENT_AUTH_INVALID")
    assert new_key.status_code == 200


def test_agent_cannot_read_another_agents_request(client, agent_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "owned-request"}, json=tool_call())
    limited_headers = {"Authorization": "Bearer ag_demo_limited_local_only"}
    forbidden = client.get(f"/api/v1/requests/{created.json()['request_id']}", headers=limited_headers)
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "REQUEST_FORBIDDEN")


def test_rejected_approval_creates_no_execution_job(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "reject"},
        json=tool_call("customers.update", {"customer_id": CUSTOMER_ID, "status": "SUSPENDED"})).json()
    rejected = client.post(f"/api/v1/approvals/{created['approval_id']}/reject", headers=admin_headers, json={"note": "not justified"})
    assert rejected.status_code == 200
    assert rejected.json()["request"]["status"] == "REJECTED"
    with SessionLocal() as db:
        assert db.get(ExecutionJob, created["request_id"]) is None


def test_expired_approval_cannot_release_job(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "expired"},
        json=tool_call("customers.update", {"customer_id": CUSTOMER_ID, "status": "SUSPENDED"})).json()
    with SessionLocal() as db:
        approval = db.get(Approval, created["approval_id"])
        approval.expires_at = now() - timedelta(seconds=1)
        db.commit()
    expired = client.post(f"/api/v1/approvals/{created['approval_id']}/approve", headers=admin_headers, json={"note": "late"})
    assert (expired.status_code, expired.json()["error"]["code"]) == (409, "APPROVAL_EXPIRED")
    with SessionLocal() as db:
        assert db.get(Approval, created["approval_id"]).status == "EXPIRED"
        assert db.get(ActionRequest, created["request_id"]).status == "EXPIRED"
        assert db.get(ExecutionJob, created["request_id"]) is None


def test_policy_simulation_has_no_live_side_effects(client, admin_headers):
    version = client.get("/api/v1/policy-versions", headers=admin_headers).json()[0]
    with SessionLocal() as db:
        before = tuple(db.scalar(select(func.count()).select_from(model)) for model in (ActionRequest, Approval, ExecutionJob, MockMessage))
    simulated = client.post(f"/api/v1/policy-versions/{version['id']}/simulate", headers=admin_headers,
        json={"facts": {"risk": "HIGH", "external_destination": False}})
    assert simulated.status_code == 200
    assert simulated.json()["decision"] == "REQUIRE_APPROVAL"
    assert simulated.json()["execution_performed"] is False
    with SessionLocal() as db:
        after = tuple(db.scalar(select(func.count()).select_from(model)) for model in (ActionRequest, Approval, ExecutionJob, MockMessage))
    assert after == before


def test_policy_change_to_approval_invalidates_old_approval(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "reapproval"},
        json=tool_call("customers.update", {"customer_id": CUSTOMER_ID, "status": "SUSPENDED"})).json()
    assert client.post(f"/api/v1/approvals/{created['approval_id']}/approve", headers=admin_headers, json={"note": "approved under v1"}).status_code == 200
    version = client.post("/api/v1/policy-versions", headers=admin_headers, json={"rules": [{
        "id": "approval-v2", "priority": 100, "effect": "REQUIRE_APPROVAL",
        "reason_code": "NEW_APPROVAL", "reason": "New policy needs a fresh approval", "conditions": [],
    }]}).json()
    assert client.post(f"/api/v1/policy-versions/{version['id']}/activate", headers=admin_headers).status_code == 200

    assert tick("reapproval-worker") is False
    with SessionLocal() as db:
        approvals = db.scalars(select(Approval).where(Approval.request_id == created["request_id"]).order_by(Approval.created_at)).all()
        job = db.get(ExecutionJob, created["request_id"])
        assert [approval.status for approval in approvals] == ["INVALIDATED", "PENDING"]
        assert job.status == "AWAITING_APPROVAL"
        fresh_approval_id = approvals[-1].id

    assert client.post(f"/api/v1/approvals/{fresh_approval_id}/approve", headers=admin_headers, json={"note": "approved under v2"}).status_code == 200
    assert tick("reapproval-worker") is True
    with SessionLocal() as db:
        assert db.get(ExecutionJob, created["request_id"]).status == "SUCCEEDED"


def test_unsafe_policy_and_tool_configuration_is_rejected(client, admin_headers):
    duplicate_rules = [{
        "id": "duplicate", "priority": 1, "effect": "ALLOW",
        "reason_code": "A", "reason": "a", "conditions": [],
    }, {
        "id": "duplicate", "priority": 2, "effect": "DENY",
        "reason_code": "B", "reason": "b", "conditions": [],
    }]
    invalid_policy = client.post("/api/v1/policy-versions", headers=admin_headers, json={"rules": duplicate_rules})
    assert (invalid_policy.status_code, invalid_policy.json()["error"]["code"]) == (422, "INVALID_POLICY")

    open_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    invalid_schema = client.post("/api/v1/tools", headers=admin_headers, json={
        "name": "unsafe.schema", "adapter_name": "documents_search", "schema": open_schema,
        "risk": "LOW", "data_classification": "INTERNAL",
    })
    assert (invalid_schema.status_code, invalid_schema.json()["error"]["code"]) == (422, "INVALID_TOOL_SCHEMA")

    closed_schema = {**open_schema, "additionalProperties": False}
    invalid_adapter = client.post("/api/v1/tools", headers=admin_headers, json={
        "name": "unsafe.adapter", "adapter_name": "arbitrary_python", "schema": closed_schema,
        "risk": "LOW", "data_classification": "INTERNAL",
    })
    assert (invalid_adapter.status_code, invalid_adapter.json()["error"]["code"]) == (422, "ADAPTER_NOT_ALLOWLISTED")


def test_token_budget_is_enforced_before_request_creation(client, agent_headers, admin_headers):
    configured = client.put("/api/v1/budgets", headers=admin_headers, json={
        "agent_id": FULL_AGENT_ID, "model": "mock-secure-v1", "request_limit": 100, "token_limit": 1,
    })
    assert configured.status_code == 200
    response = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "token-budget"}, json=tool_call())
    assert (response.status_code, response.json()["error"]["code"]) == (429, "BUDGET_EXHAUSTED")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ActionRequest)) == 0


def test_provider_unavailability_is_audited(client, admin_headers):
    response = client.post("/api/v1/agent-runs", headers=admin_headers, json={
        "agent_id": FULL_AGENT_ID, "user_id": ADMIN_ID, "prompt": "test", "scenario": "PROVIDER_UNAVAILABLE",
    })
    assert (response.status_code, response.json()["error"]["code"]) == (503, "PROVIDER_UNAVAILABLE")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "LLM_PROVIDER_UNAVAILABLE")) == 1


def test_approval_views_redact_message_content(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "redaction"},
        json=tool_call("messages.send", {"destination": "partner@example.com", "message": "customer summary"})).json()
    approval = client.get(f"/api/v1/approvals/{created['approval_id']}", headers=admin_headers)
    assert approval.status_code == 200
    assert approval.json()["arguments"] == {"destination": "partner@example.com", "message": "[REDACTED]"}


def test_audit_text_search_accepts_action_id(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "audit-action-search"},
        json=tool_call()).json()
    response = client.get(f"/api/v1/audit-events?q={created['request_id']}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["items"]
    assert {event["request_id"] for event in response.json()["items"]} == {created["request_id"]}
