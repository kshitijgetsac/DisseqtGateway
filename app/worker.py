import os
import time
from datetime import timedelta, timezone
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from .core import audit, cleanup_execution_job, reevaluate_before_execution
from .db import Base, SessionLocal, engine
from .models import Agent, AgentToolPermission, ActionRequest, Approval, ExecutionAttempt, ExecutionJob, MockCustomer, MockDocument, MockMessage, Tool, User, WorkerHeartbeat, now


def cleanup_expired_approvals(db: Session) -> int:
    """Expire pending approvals and remove jobs that can no longer execute."""
    current = now()
    approvals = db.scalars(select(Approval).where(
        Approval.status == "PENDING", Approval.expires_at <= current,
    ).with_for_update(skip_locked=True)).all()
    for approval in approvals:
        req = db.scalar(select(ActionRequest).where(ActionRequest.id == approval.request_id).with_for_update())
        approval.status = "EXPIRED"
        req.status = "EXPIRED"
        cleanup_execution_job(db, req, "APPROVAL_EXPIRED")
        audit(db, "APPROVAL_EXPIRED", request=req, details={"approval_id": approval.id})
    if approvals:
        db.commit()
    return len(approvals)


def execution_authorization_failure(db: Session, req: ActionRequest) -> str | None:
    """Recheck mutable authorization immediately before the adapter side effect."""
    agent = db.scalar(select(Agent).where(Agent.id == req.agent_id).with_for_update())
    user = db.scalar(select(User).where(User.id == req.user_id).with_for_update())
    tool = db.scalar(select(Tool).where(Tool.id == req.tool_id).with_for_update())
    if not agent or not agent.active:
        return "AGENT_DISABLED"
    if not user or not user.active:
        return "USER_DISABLED"
    if agent.owner_id != user.id:
        return "AGENT_USER_DELEGATION_REVOKED"
    if not tool or not tool.active:
        return "TOOL_DISABLED"
    permission = db.scalar(select(AgentToolPermission).where(
        AgentToolPermission.agent_id == agent.id,
        AgentToolPermission.tool_id == tool.id,
    ).with_for_update())
    return None if permission else "AGENT_TOOL_PERMISSION_REVOKED"


def claim_job(db: Session, worker_id: str) -> str | None:
    current = now()
    stmt = select(ExecutionJob).where(or_(
        (ExecutionJob.status == "PENDING") & (or_(ExecutionJob.next_attempt_at.is_(None), ExecutionJob.next_attempt_at <= current)),
        (ExecutionJob.status == "RUNNING") & (ExecutionJob.lease_until < current),
    )).order_by(ExecutionJob.created_at).with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if not job:
        return None
    req = db.scalar(select(ActionRequest).where(ActionRequest.id == job.request_id).with_for_update())
    if job.status == "RUNNING":
        expired_attempt = db.scalar(select(ExecutionAttempt).where(
            ExecutionAttempt.request_id == job.request_id,
            ExecutionAttempt.attempt_number == job.attempt_count,
        ).with_for_update())
        if expired_attempt and expired_attempt.status == "RUNNING":
            expired_attempt.status = "LEASE_EXPIRED"
            expired_attempt.completed_at = current
            expired_attempt.error_code = "WORKER_LEASE_EXPIRED"
        audit(db, "WORKER_LEASE_EXPIRED", request=req, actor_type="WORKER", actor_id=job.worker_id,
              details={"attempt_number": job.attempt_count,
                       "lease_until": job.lease_until.isoformat() if job.lease_until else None})
    if not reevaluate_before_execution(db, req, job):
        db.commit()
        return None
    if job.attempt_count >= 3:
        job.status = "OUTCOME_UNKNOWN"
        req.status = "OUTCOME_UNKNOWN"
        audit(db, "EXECUTION_OUTCOME_UNKNOWN", request=req, details={"attempt_count": job.attempt_count})
        db.commit()
        return None
    job.status = "RUNNING"
    job.worker_id = worker_id
    job.lease_until = current + timedelta(seconds=30)
    job.attempt_count += 1
    req.status = "RUNNING"
    db.add(ExecutionAttempt(request_id=req.id, attempt_number=job.attempt_count, status="RUNNING"))
    audit(db, "JOB_CLAIMED", request=req, actor_type="WORKER", actor_id=worker_id,
          details={"attempt_number": job.attempt_count, "policy_version_id": req.current_policy_version_id})
    db.commit()
    return req.id


def execute_mock(db: Session, req: ActionRequest) -> dict:
    tool = db.get(Tool, req.tool_id)
    args = req.arguments
    if tool.adapter_name == "documents_search":
        query = args["query"].lower()
        docs = db.scalars(select(MockDocument)).all()
        return {"documents": [{"id": d.id, "title": d.title, "classification": d.classification,
                 "content": d.content} for d in docs if query in d.title.lower() or query in d.content.lower()]}
    if tool.adapter_name == "customers_update":
        customer = db.scalar(select(MockCustomer).where(MockCustomer.id == args["customer_id"]).with_for_update())
        if not customer:
            raise ValueError("CUSTOMER_NOT_FOUND")
        customer.status = args["status"]
        return {"customer_id": customer.id, "status": customer.status}
    if tool.adapter_name == "messages_send":
        existing = db.scalar(select(MockMessage).where(MockMessage.idempotency_key == req.id))
        if not existing:
            existing = MockMessage(idempotency_key=req.id, destination=args["destination"], message=args["message"])
            db.add(existing)
            db.flush()
        return {"message_id": existing.id, "destination": existing.destination}
    raise ValueError("ADAPTER_NOT_ALLOWLISTED")


def finish_job(db: Session, request_id: str, worker_id: str):
    job = db.scalar(select(ExecutionJob).where(ExecutionJob.request_id == request_id).with_for_update())
    if not job or job.status != "RUNNING" or job.worker_id != worker_id:
        return
    req = db.scalar(select(ActionRequest).where(ActionRequest.id == request_id).with_for_update())
    attempt = db.scalar(select(ExecutionAttempt).where(ExecutionAttempt.request_id == request_id,
        ExecutionAttempt.attempt_number == job.attempt_count))
    authorization_failure = execution_authorization_failure(db, req)
    if authorization_failure:
        req.status = "CANCELLED"
        job.status = "CANCELLED"
        job.last_error = authorization_failure
        job.lease_until = None
        attempt.status = "CANCELLED"
        attempt.completed_at = now()
        attempt.error_code = authorization_failure
        audit(db, "EXECUTION_AUTHORIZATION_REVOKED", request=req, actor_type="WORKER", actor_id=worker_id,
              reason_code=authorization_failure, details={"attempt_number": job.attempt_count})
        db.commit()
        return
    try:
        # Mock side effect and receipt commit together. Real external adapters would
        # require their own idempotency key or an OUTCOME_UNKNOWN reconciliation path.
        with db.begin_nested():
            result = execute_mock(db, req)
        job.result = result
        job.status = "SUCCEEDED"
        req.status = "SUCCEEDED"
        attempt.status = "SUCCEEDED"
        audit(db, "EXECUTION_SUCCEEDED", request=req, actor_type="WORKER", actor_id=worker_id,
              details={"attempt_number": job.attempt_count, "result": result})
    except Exception as exc:
        code = str(exc)[:100]
        retryable = code not in {"CUSTOMER_NOT_FOUND", "ADAPTER_NOT_ALLOWLISTED"}
        job.status = "PENDING" if retryable and job.attempt_count < 3 else "FAILED"
        job.next_attempt_at = now() + timedelta(seconds=2 ** job.attempt_count) if job.status == "PENDING" else None
        job.last_error = code
        req.status = "RETRYING" if job.status == "PENDING" else "FAILED"
        attempt.status = "FAILED"
        attempt.error_code = code
        audit(db, "EXECUTION_FAILED", request=req, actor_type="WORKER", actor_id=worker_id,
              details={"attempt_number": job.attempt_count, "error_code": code, "retryable": retryable})
    attempt.completed_at = now()
    job.lease_until = None
    db.commit()


def tick(worker_id="worker-1") -> bool:
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if not heartbeat:
            heartbeat = WorkerHeartbeat(id=worker_id)
            db.add(heartbeat)
        heartbeat.last_seen_at = now()
        db.commit()
        cleanup_expired_approvals(db)
        request_id = claim_job(db, worker_id)
    if not request_id:
        return False
    with SessionLocal() as db:
        finish_job(db, request_id, worker_id)
    return True


if __name__ == "__main__":
    from .seed import initialize
    initialize()
    worker_id = os.getenv("WORKER_ID", "worker-1")
    while True:
        try:
            worked = tick(worker_id)
            if not worked:
                time.sleep(0.5)
        except Exception as exc:
            print(f"Worker tick failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(1)
