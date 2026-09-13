import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .contracts import ToolCallIn
from .errors import GatewayError
from .models import Agent, AgentToolPermission, ActionRequest, Approval, AuditEvent, ExecutionAttempt, ExecutionJob, MockCustomer, MockDocument, MockMessage, Policy, PolicyVersion, Tool, UsageBucket, User, now
from .policy import evaluate, validate_arguments


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def redacted(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in {"message", "content", "prompt", "api_key", "token"} else redacted(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redacted(v) for v in value]
    return value


def audit(db: Session, event_type: str, *, request: ActionRequest | None = None, actor_type="SYSTEM", actor_id=None, policy_version_id=None, decision=None, reason_code=None, details=None) -> AuditEvent:
    event = AuditEvent(request_id=request.id if request else None, event_type=event_type, actor_type=actor_type, actor_id=actor_id,
                       agent_id=request.agent_id if request else None, user_id=request.user_id if request else None,
                       tool_id=request.tool_id if request else None, policy_version_id=policy_version_id,
                       decision=decision, risk=request.facts.get("risk") if request else None,
                       reason_code=reason_code, details=redacted(details or {}))
    db.add(event)
    db.flush()
    return event


def active_policy(db: Session) -> PolicyVersion:
    policy = db.scalar(select(Policy).where(Policy.name == "gateway"))
    if not policy or not policy.active_version_id:
        raise GatewayError(503, "NO_ACTIVE_POLICY", "No active policy is configured.")
    return db.get(PolicyVersion, policy.active_version_id)


def facts_for(db: Session, agent: Agent, user: User, tool: Tool, body: ToolCallIn) -> dict:
    destination = str(body.arguments.get("destination", ""))
    external = bool(destination and not destination.lower().endswith("@internal.example"))
    sensitive = bool(re.search(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:secret|confidential|restricted)\b", json.dumps(body.arguments), re.I))
    injection = False
    classification = tool.data_classification
    classes = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}
    for item in body.untrusted_context:
        # Only a server-side artifact lookup can establish classification.
        doc = db.get(MockDocument, item.artifact_id) if item.artifact_id else None
        if doc and classes[doc.classification] > classes[classification]:
            classification = doc.classification
        if doc and doc.classification in {"CONFIDENTIAL", "RESTRICTED"} and doc.content in json.dumps(body.arguments):
            sensitive = True
        if re.search(r"ignore (?:previous|all) instructions|bypass (?:the )?gateway|system prompt", item.content, re.I):
            injection = True
    return {"agent_id": agent.id, "user_id": user.id, "tool": tool.name, "tool_id": tool.id, "risk": tool.risk,
            "data_classification": classification, "environment": body.environment, "destination": destination,
            "external_destination": external, "sensitive_payload": sensitive, "prompt_injection": injection, "model": body.model}


def reserve_budget(db: Session, agent_id: str, model: str, tokens: int, scope="GATEWAY_ACTION"):
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    values = dict(agent_id=agent_id, model=model, scope=scope, window_start=start,
                  request_limit=100, token_limit=10000, used_requests=0, used_tokens=0)
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(UsageBucket).values(**values).on_conflict_do_nothing(
        index_elements=["agent_id", "model", "scope", "window_start"]))
    result = db.execute(update(UsageBucket).where(UsageBucket.agent_id == agent_id, UsageBucket.model == model,
        UsageBucket.scope == scope, UsageBucket.window_start == start,
        UsageBucket.used_requests < UsageBucket.request_limit,
        UsageBucket.used_tokens + tokens <= UsageBucket.token_limit).values(
        used_requests=UsageBucket.used_requests + 1, used_tokens=UsageBucket.used_tokens + tokens))
    if result.rowcount != 1:
        raise GatewayError(429, "BUDGET_EXHAUSTED", "Request or token budget exhausted.")


def reconcile_budget(db: Session, agent_id: str, model: str, reserved_tokens: int,
                     actual_tokens: int, scope="LLM_PROVIDER"):
    """Release unused provider tokens while retaining the charged invocation count."""
    if actual_tokens > reserved_tokens:
        raise RuntimeError("Provider usage exceeded its deterministic reservation")
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    db.execute(update(UsageBucket).where(
        UsageBucket.agent_id == agent_id,
        UsageBucket.model == model,
        UsageBucket.scope == scope,
        UsageBucket.window_start == start,
    ).values(used_tokens=UsageBucket.used_tokens - (reserved_tokens - actual_tokens)))


def request_view(db: Session, req: ActionRequest) -> dict:
    approval = db.scalar(select(Approval).where(Approval.request_id == req.id).order_by(Approval.expires_at.desc()))
    job = db.get(ExecutionJob, req.id)
    policy = db.get(PolicyVersion, req.current_policy_version_id)
    return {"request_id": req.id, "decision": req.current_decision, "initial_decision": req.initial_decision,
            "status": req.status, "reason_code": req.reason_code, "reason": req.reason,
            "policy": {"version": policy.version, "version_id": policy.id},
            "approval_id": approval.id if approval and approval.status == "PENDING" else None,
            "approval_status": approval.status if approval else None,
            "execution": {"status": job.status, "attempt_count": job.attempt_count, "result": redacted(job.result)} if job else None}


def cancel_execution_job(db: Session, req: ActionRequest, reason_code: str) -> bool:
    """Make a job terminal while preserving its execution and attempt history."""
    job = db.scalar(select(ExecutionJob).where(ExecutionJob.request_id == req.id).with_for_update())
    if not job:
        return False
    previous_status = job.status
    job.status = "CANCELLED"
    job.last_error = reason_code
    job.lease_until = None
    job.next_attempt_at = None
    running_attempts = db.scalars(select(ExecutionAttempt).where(
        ExecutionAttempt.request_id == req.id,
        ExecutionAttempt.status == "RUNNING",
    ).with_for_update()).all()
    for attempt in running_attempts:
        attempt.status = "CANCELLED"
        attempt.completed_at = now()
        attempt.error_code = reason_code
    audit(db, "EXECUTION_JOB_CANCELLED", request=req, reason_code=reason_code,
          details={"previous_status": previous_status})
    return True


def submit_tool_call(db: Session, agent: Agent, body: ToolCallIn, key: str) -> dict:
    if not key or len(key) > 200:
        raise GatewayError(400, "IDEMPOTENCY_KEY_REQUIRED", "A valid Idempotency-Key header is required.")
    canonical = body.model_dump(mode="json")
    request_digest = digest(canonical)
    existing = db.scalar(select(ActionRequest).where(ActionRequest.agent_id == agent.id, ActionRequest.idempotency_key == key))
    if existing:
        if existing.request_digest != request_digest:
            raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "This key was used for a different request.", existing.id)
        return request_view(db, existing)
    user = db.get(User, body.user_id)
    if not user or not user.active:
        db.add(AuditEvent(event_type="AUTHORIZATION_FAILED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=body.user_id, reason_code="USER_AUTH_INVALID", details={}))
        db.commit()
        raise GatewayError(401, "USER_AUTH_INVALID", "Acting user is unknown or disabled.")
    if user.id != agent.owner_id:
        db.add(AuditEvent(event_type="AUTHORIZATION_FAILED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, reason_code="AGENT_USER_DELEGATION_MISSING", details={}))
        db.commit()
        raise GatewayError(403, "AGENT_USER_DELEGATION_MISSING", "Agent is not authorized to act for this user.")
    tool = db.scalar(select(Tool).where(Tool.name == body.tool))
    if not tool:
        db.add(AuditEvent(event_type="TOOL_LOOKUP_FAILED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, reason_code="TOOL_NOT_FOUND", details={"tool": body.tool}))
        db.commit()
        raise GatewayError(404, "TOOL_NOT_FOUND", "Tool not found.")
    if not tool.active:
        db.add(AuditEvent(event_type="AUTHORIZATION_FAILED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, tool_id=tool.id, risk=tool.risk,
            reason_code="TOOL_DISABLED", details={}))
        db.commit()
        raise GatewayError(403, "TOOL_DISABLED", "Tool is disabled.")
    permission = db.scalar(select(AgentToolPermission).where(AgentToolPermission.agent_id == agent.id, AgentToolPermission.tool_id == tool.id))
    if not permission:
        db.add(AuditEvent(event_type="AUTHORIZATION_FAILED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, tool_id=tool.id, risk=tool.risk,
            reason_code="AGENT_TOOL_PERMISSION_MISSING", details={}))
        db.commit()
        raise GatewayError(403, "AGENT_TOOL_PERMISSION_MISSING", "The agent is not authorized for this tool action.")
    if body.model != "mock-secure-v1":
        db.add(AuditEvent(event_type="MODEL_REJECTED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, tool_id=tool.id, risk=tool.risk,
            reason_code="MODEL_NOT_ALLOWED", details={"model": body.model}))
        db.commit()
        raise GatewayError(403, "MODEL_NOT_ALLOWED", "Model is not in the allowlist.")
    try:
        validate_arguments(tool.schema, body.arguments)
    except GatewayError:
        db.add(AuditEvent(event_type="TOOL_ARGUMENTS_REJECTED", actor_type="AGENT", actor_id=agent.id,
            agent_id=agent.id, user_id=user.id, tool_id=tool.id, risk=tool.risk,
            reason_code="INVALID_TOOL_ARGUMENTS", details={"argument_keys": sorted(body.arguments)}))
        db.commit()
        raise
    version = active_policy(db)
    facts = facts_for(db, agent, user, tool, body)
    outcome = evaluate(version.rules, facts)
    # The mock provider budgets a deterministic estimate for each tool call.
    reserve_budget(db, agent.id, body.model, max(1, len(json.dumps(canonical)) // 4))
    req = ActionRequest(agent_id=agent.id, user_id=user.id, tool_id=tool.id, idempotency_key=key,
        request_digest=request_digest, model=body.model, arguments=body.arguments, facts=facts,
        environment=body.environment, initial_decision=outcome["decision"], current_decision=outcome["decision"],
        status={"ALLOW": "QUEUED", "DENY": "DENIED", "REQUIRE_APPROVAL": "PENDING_APPROVAL"}[outcome["decision"]],
        initial_policy_version_id=version.id, current_policy_version_id=version.id,
        reason_code=outcome["reason_code"], reason=outcome["reason"])
    db.add(req)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ActionRequest).where(ActionRequest.agent_id == agent.id, ActionRequest.idempotency_key == key))
        if not existing or existing.request_digest != request_digest:
            raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "This key was used for a different request.")
        return request_view(db, existing)
    decision_event = audit(db, "POLICY_EVALUATED", request=req, policy_version_id=version.id,
        decision=outcome["decision"], reason_code=outcome["reason_code"],
        details={"mode": "LIVE", "facts": facts, "matched_rule_ids": outcome["matched_rule_ids"],
                 "winning_priority": outcome["winning_priority"], "request_digest": request_digest})
    if outcome["decision"] == "ALLOW":
        db.add(ExecutionJob(request_id=req.id))
    elif outcome["decision"] == "REQUIRE_APPROVAL":
        approval = Approval(request_id=req.id, decision_event_id=decision_event.id, request_digest=request_digest,
            expires_at=now() + timedelta(minutes=30))
        db.add(approval)
        db.flush()
        audit(db, "APPROVAL_REQUESTED", request=req, policy_version_id=version.id, details={"approval_id": approval.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ActionRequest).where(ActionRequest.agent_id == agent.id, ActionRequest.idempotency_key == key))
        if not existing or existing.request_digest != request_digest:
            raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "This key was used for a different request.")
        return request_view(db, existing)
    return request_view(db, req)


def resolve_approval(db: Session, approval_id: str, user: User, approve: bool, note: str) -> dict:
    approval = db.scalar(select(Approval).where(Approval.id == approval_id).with_for_update())
    if not approval:
        raise GatewayError(404, "APPROVAL_NOT_FOUND", "Approval not found.")
    req = db.scalar(select(ActionRequest).where(ActionRequest.id == approval.request_id).with_for_update())
    if approval.status != "PENDING":
        raise GatewayError(409, "APPROVAL_ALREADY_RESOLVED", "Approval already has a final state.", req.id,
            {"approval_status": approval.status})
    if approval.expires_at.replace(tzinfo=timezone.utc) <= now():
        approval.status = "EXPIRED"
        req.status = "EXPIRED"
        cancel_execution_job(db, req, "APPROVAL_EXPIRED")
        audit(db, "APPROVAL_EXPIRED", request=req, actor_type="HUMAN", actor_id=user.id)
        db.commit()
        raise GatewayError(409, "APPROVAL_EXPIRED", "Approval has expired.", req.id)
    if req.request_digest != approval.request_digest:
        raise GatewayError(409, "APPROVAL_STALE", "The action has changed since approval was requested.", req.id)
    approval.status = "APPROVED" if approve else "REJECTED"
    approval.note = note
    approval.decided_at = now()
    approval.decided_by_user_id = user.id
    req.status = "QUEUED" if approve else "REJECTED"
    if approve:
        job = db.get(ExecutionJob, req.id)
        if not job:
            db.add(ExecutionJob(request_id=req.id))
        elif job.status == "AWAITING_APPROVAL":
            job.status = "PENDING"
            job.next_attempt_at = None
    else:
        cancel_execution_job(db, req, "APPROVAL_REJECTED")
    audit(db, "APPROVAL_APPROVED" if approve else "APPROVAL_REJECTED", request=req,
          actor_type="HUMAN", actor_id=user.id, policy_version_id=req.current_policy_version_id,
          details={"approval_id": approval.id, "note": note})
    db.commit()
    return {"approval_id": approval.id, "status": approval.status, "request": request_view(db, req)}


def reevaluate_before_execution(db: Session, req: ActionRequest, job: ExecutionJob) -> bool:
    # Called with locked job and request rows. Policy activation locks the same policy row.
    policy = db.scalar(select(Policy).where(Policy.name == "gateway").with_for_update())
    if req.current_policy_version_id == policy.active_version_id:
        return True
    version = db.get(PolicyVersion, policy.active_version_id)
    outcome = evaluate(version.rules, req.facts)
    req.current_policy_version_id = version.id
    req.current_decision = outcome["decision"]
    req.reason_code = outcome["reason_code"]
    req.reason = outcome["reason"]
    decision_event = audit(db, "POLICY_REEVALUATED", request=req, policy_version_id=version.id,
        decision=outcome["decision"], reason_code=outcome["reason_code"],
        details={"mode": "LIVE", "facts": req.facts, "matched_rule_ids": outcome["matched_rule_ids"],
                 "winning_priority": outcome["winning_priority"], "request_digest": req.request_digest})
    for approval in db.scalars(select(Approval).where(Approval.request_id == req.id, Approval.status == "APPROVED")):
        approval.status = "INVALIDATED"
    if outcome["decision"] == "DENY":
        job.status = "CANCELLED"
        req.status = "DENIED"
        return False
    if outcome["decision"] == "REQUIRE_APPROVAL":
        job.status = "AWAITING_APPROVAL"
        req.status = "PENDING_APPROVAL"
        new_approval = Approval(request_id=req.id, decision_event_id=decision_event.id,
            request_digest=req.request_digest, expires_at=now() + timedelta(minutes=30))
        db.add(new_approval)
        db.flush()
        audit(db, "APPROVAL_REQUESTED", request=req, policy_version_id=version.id,
              details={"approval_id": new_approval.id, "reapproval": True})
        return False
    return True
