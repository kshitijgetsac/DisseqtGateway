from typing import Any, Literal
from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    source: str
    content: str = ""
    classification: str | None = None
    artifact_id: str | None = None


class ToolCallIn(BaseModel):
    user_id: str
    model: str
    tool: str
    arguments: dict[str, Any]
    environment: Literal["DEVELOPMENT", "STAGING", "PRODUCTION"] = "DEVELOPMENT"
    untrusted_context: list[ContextItem] = Field(default_factory=list)


class AgentRunIn(BaseModel):
    agent_id: str
    user_id: str
    prompt: str
    scenario: str


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    owner_id: str


class AgentPatch(BaseModel):
    name: str | None = None
    owner_id: str | None = None


class PermissionIn(BaseModel):
    tool_ids: list[str]


class ToolIn(BaseModel):
    name: str
    adapter_name: str
    schema_: dict = Field(alias="schema")
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


class ToolPatch(BaseModel):
    name: str | None = None
    schema_: dict | None = Field(default=None, alias="schema")
    risk: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"] | None = None


class RuleIn(BaseModel):
    id: str
    priority: int
    effect: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]
    reason_code: str
    reason: str
    conditions: list[dict] = Field(default_factory=list)


class PolicyVersionIn(BaseModel):
    policy_id: str | None = None
    rules: list[RuleIn]


class SimulateIn(BaseModel):
    facts: dict[str, Any]


class ReplayIn(BaseModel):
    target_policy_version_id: str


class BudgetIn(BaseModel):
    agent_id: str
    model: str = "mock-secure-v1"
    scope: Literal["GATEWAY_ACTION", "LLM_PROVIDER"] = "GATEWAY_ACTION"
    request_limit: int = Field(gt=0)
    token_limit: int = Field(gt=0)
