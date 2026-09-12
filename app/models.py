from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="VIEWER")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    adapter_name: Mapped[str] = mapped_column(String(50))
    schema: Mapped[dict] = mapped_column(JSON)
    risk: Mapped[str] = mapped_column(String(20))
    data_classification: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentToolPermission(Base):
    __tablename__ = "agent_tool_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"))


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"))
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[list] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ActionRequest(Base):
    __tablename__ = "action_requests"
    __table_args__ = (UniqueConstraint("agent_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_digest: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON)
    facts: Mapped[dict] = mapped_column(JSON)
    environment: Mapped[str] = mapped_column(String(30))
    initial_decision: Mapped[str] = mapped_column(String(30))
    current_decision: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    initial_policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    current_policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    reason_code: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"))
    decision_event_id: Mapped[str] = mapped_column(ForeignKey("audit_events.id"))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"
    request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey("execution_jobs.request_id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class UsageBucket(Base):
    __tablename__ = "usage_buckets"
    __table_args__ = (UniqueConstraint("agent_id", "model", "window_start"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    model: Mapped[str] = mapped_column(String(100))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_limit: Mapped[int] = mapped_column(Integer, default=100)
    token_limit: Mapped[int] = mapped_column(Integer, default=10000)
    used_requests: Mapped[int] = mapped_column(Integer, default=0)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("action_requests.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60))
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    policy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MockDocument(Base):
    __tablename__ = "mock_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(20))


class MockCustomer(Base):
    __tablename__ = "mock_customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))


class MockMessage(Base):
    __tablename__ = "mock_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    destination: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
