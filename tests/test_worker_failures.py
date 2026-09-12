from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ActionRequest, ExecutionAttempt, ExecutionJob, now
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
