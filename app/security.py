import hashlib
import secrets
from fastapi import Header
from sqlalchemy import select
from sqlalchemy.orm import Session
from .errors import GatewayError
from .models import Agent, AuditEvent, User


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return "ag_" + secrets.token_urlsafe(32)


def agent_from_bearer(db: Session, authorization: str | None) -> Agent:
    if not authorization or not authorization.startswith("Bearer "):
        db.add(AuditEvent(event_type="AUTHENTICATION_FAILED", actor_type="AGENT", reason_code="AGENT_AUTH_REQUIRED", details={}))
        db.commit()
        raise GatewayError(401, "AGENT_AUTH_REQUIRED", "A valid agent bearer key is required.")
    key = authorization[7:]
    agent = db.scalar(select(Agent).where(Agent.api_key_hash == hash_key(key)))
    if not agent or not agent.active:
        db.add(AuditEvent(event_type="AUTHENTICATION_FAILED", actor_type="AGENT", reason_code="AGENT_AUTH_INVALID", details={}))
        db.commit()
        raise GatewayError(401, "AGENT_AUTH_INVALID", "Agent key is invalid or agent is disabled.")
    return agent


def human_from_header(db: Session, user_id: str | None, allowed: set[str] | None = None) -> User:
    if not user_id:
        raise GatewayError(401, "USER_AUTH_REQUIRED", "X-Demo-User-Id is required.")
    user = db.get(User, user_id)
    if not user or not user.active:
        raise GatewayError(401, "USER_AUTH_INVALID", "Demo user is unknown or disabled.")
    if allowed and user.role not in allowed:
        raise GatewayError(403, "ROLE_FORBIDDEN", "This user cannot perform the operation.")
    return user
