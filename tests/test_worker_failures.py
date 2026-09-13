from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ActionRequest, Approval, AuditEvent, ExecutionAttempt, ExecutionJob, MockMessage, now
from app.worker import claim_job, finish_job, tick
from conftest import tool_call


def test_non_retryable_adapter_failure_is_terminal(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "missing-customer"},
        json=tool_call("customers.update", {"customer_id": "missing", "status": "SUSPENDED"})).json()
    client.post(f"/api/v1/approvals/{created['approval_id']}/approve", headers=admin_headers, json={"note": "exercise failure"})
    assert tick("terminal-worker") is True
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        attempt = db.scalar(select(ExecutionAttempt).where(ExecutionAttempt.request_id == created["request_id"]))
        assert (job.status, job.last_error, job.attempt_count) == ("FAILED", "CUSTOMER_NOT_FOUND", 1)
        assert (attempt.status, attempt.error_code) == ("FAILED", "CUSTOMER_NOT_FOUND")


def test_retryable_adapter_failure_stops_after_three_attempts(client, agent_headers, monkeypatch):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "retryable"}, json=tool_call()).json()

    def fail_temporarily(*_):
        raise RuntimeError("TEMPORARY_PROVIDER_ERROR")

    monkeypatch.setattr("app.worker.execute_mock", fail_temporarily)
    for attempt_number in range(1, 4):
        assert tick(f"retry-worker-{attempt_number}") is True
        with SessionLocal() as db:
            job = db.get(ExecutionJob, created["request_id"])
            if attempt_number < 3:
                assert job.status == "PENDING"
                job.next_attempt_at = now() - timedelta(seconds=1)
                db.commit()

    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        attempts = db.scalars(select(ExecutionAttempt).where(ExecutionAttempt.request_id == created["request_id"])).all()
        assert (job.status, job.attempt_count) == ("FAILED", 3)
        assert [attempt.status for attempt in attempts] == ["FAILED", "FAILED", "FAILED"]


def test_stale_worker_cannot_finish_after_job_is_reclaimed(client, agent_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "stale-worker"}, json=tool_call()).json()
    with SessionLocal() as db:
        assert claim_job(db, "worker-a") == created["request_id"]
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        job.lease_until = now() - timedelta(seconds=1)
        db.commit()
    with SessionLocal() as db:
        assert claim_job(db, "worker-b") == created["request_id"]
    with SessionLocal() as db:
        finish_job(db, created["request_id"], "worker-a")
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        assert (job.status, job.worker_id, job.attempt_count) == ("RUNNING", "worker-b", 2)
    with SessionLocal() as db:
        finish_job(db, created["request_id"], "worker-b")
    with SessionLocal() as db:
        assert db.get(ExecutionJob, created["request_id"]).status == "SUCCEEDED"
        attempts = db.scalars(select(ExecutionAttempt).where(
            ExecutionAttempt.request_id == created["request_id"],
        ).order_by(ExecutionAttempt.attempt_number)).all()
        assert [attempt.status for attempt in attempts] == ["LEASE_EXPIRED", "SUCCEEDED"]
        assert attempts[0].error_code == "WORKER_LEASE_EXPIRED"


def test_three_lost_worker_leases_end_as_outcome_unknown(client, agent_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "unknown-outcome"}, json=tool_call()).json()
    for number in range(1, 4):
        with SessionLocal() as db:
            assert claim_job(db, f"crashed-worker-{number}") == created["request_id"]
        with SessionLocal() as db:
            job = db.get(ExecutionJob, created["request_id"])
            job.lease_until = now() - timedelta(seconds=1)
            db.commit()
    with SessionLocal() as db:
        assert claim_job(db, "reconciler") is None
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        request = db.get(ActionRequest, created["request_id"])
        assert job.status == request.status == "OUTCOME_UNKNOWN"
        attempts = db.scalars(select(ExecutionAttempt).where(
            ExecutionAttempt.request_id == created["request_id"],
        ).order_by(ExecutionAttempt.attempt_number)).all()
        assert [attempt.status for attempt in attempts] == ["LEASE_EXPIRED"] * 3


def test_worker_rechecks_agent_permission_immediately_before_execution(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "permission-revoked"},
        json=tool_call("messages.send", {"destination": "partner@example.com", "message": "hello"})).json()
    client.post(f"/api/v1/approvals/{created['approval_id']}/approve", headers=admin_headers, json={"note": "initially allowed"})
    with SessionLocal() as db:
        assert claim_job(db, "permission-worker") == created["request_id"]

    agent_id = "00000000-0000-0000-0000-000000000010"
    tools = client.get("/api/v1/tools", headers=admin_headers).json()
    retained = [tool["id"] for tool in tools if tool["name"] != "messages.send"]
    assert client.put(f"/api/v1/agents/{agent_id}/permissions", headers=admin_headers,
                      json={"tool_ids": retained}).status_code == 200

    with SessionLocal() as db:
        finish_job(db, created["request_id"], "permission-worker")
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        assert (job.status, job.last_error) == ("CANCELLED", "AGENT_TOOL_PERMISSION_REVOKED")
        assert db.get(ActionRequest, created["request_id"]).status == "CANCELLED"
        assert db.scalars(select(MockMessage)).all() == []
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.request_id == created["request_id"],
            AuditEvent.event_type == "EXECUTION_AUTHORIZATION_REVOKED",
        ))
        assert event.reason_code == "AGENT_TOOL_PERMISSION_REVOKED"


def test_worker_cleans_up_job_when_pending_approval_expires(client, agent_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "stale-expiry"},
        json=tool_call("customers.update", {"customer_id": "00000000-0000-0000-0000-000000000020", "status": "SUSPENDED"})).json()
    with SessionLocal() as db:
        approval = db.get(Approval, created["approval_id"])
        approval.expires_at = now() - timedelta(seconds=1)
        db.add(ExecutionJob(request_id=created["request_id"], status="AWAITING_APPROVAL"))
        db.commit()

    assert tick("expiry-cleaner") is False
    with SessionLocal() as db:
        assert db.get(Approval, created["approval_id"]).status == "EXPIRED"
        assert db.get(ActionRequest, created["request_id"]).status == "EXPIRED"
        assert db.get(ExecutionJob, created["request_id"]) is None


def test_rejection_cleans_up_awaiting_approval_job(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "stale-rejection"},
        json=tool_call("customers.update", {"customer_id": "00000000-0000-0000-0000-000000000020", "status": "SUSPENDED"})).json()
    with SessionLocal() as db:
        db.add(ExecutionJob(request_id=created["request_id"], status="AWAITING_APPROVAL"))
        db.commit()

    rejected = client.post(f"/api/v1/approvals/{created['approval_id']}/reject", headers=admin_headers,
                           json={"note": "rights not granted"})
    assert rejected.status_code == 200
    with SessionLocal() as db:
        assert db.get(ExecutionJob, created["request_id"]) is None
