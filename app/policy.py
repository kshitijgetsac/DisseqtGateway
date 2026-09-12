from jsonschema import Draft202012Validator
from .errors import GatewayError


FACT_FIELDS = {"agent_id", "user_id", "tool", "tool_id", "risk", "data_classification", "environment", "destination", "external_destination", "sensitive_payload", "prompt_injection", "model"}
OPS = {"eq", "ne", "in", "contains", "gte", "lte"}
EFFECT_RANK = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}


def validate_rules(rules: list[dict]):
    if not rules:
        raise GatewayError(422, "INVALID_POLICY", "Policy version needs at least one rule.")
    ids = set()
    for rule in rules:
        if not rule.get("id") or rule["id"] in ids:
            raise GatewayError(422, "INVALID_POLICY", "Rule IDs must be nonempty and unique.")
        ids.add(rule["id"])
        if not isinstance(rule.get("priority"), int) or not rule.get("reason_code") or rule.get("effect") not in EFFECT_RANK:
            raise GatewayError(422, "INVALID_POLICY", "Invalid priority, reason code, or effect.")
        for condition in rule.get("conditions", []):
            if set(condition) != {"field", "op", "value"} or condition["field"] not in FACT_FIELDS or condition["op"] not in OPS:
                raise GatewayError(422, "INVALID_POLICY", "Invalid policy condition.")


def condition_matches(condition: dict, facts: dict) -> bool:
    actual, value, op = facts.get(condition["field"]), condition["value"], condition["op"]
    if op == "eq": return actual == value
    if op == "ne": return actual != value
    if op == "in": return actual in value if isinstance(value, list) else False
    if op == "contains": return value in actual if isinstance(actual, (str, list)) else False
    if op == "gte": return actual is not None and actual >= value
    if op == "lte": return actual is not None and actual <= value
    return False


def evaluate(rules: list[dict], facts: dict) -> dict:
    matched = [r for r in rules if all(condition_matches(c, facts) for c in r.get("conditions", []))]
    if not matched:
        return {"decision": "DENY", "reason_code": "DEFAULT_DENY", "reason": "No policy rule allows this action.", "winning_priority": None, "matched_rule_ids": []}
    priority = max(r["priority"] for r in matched)
    winners = [r for r in matched if r["priority"] == priority]
    winner = max(winners, key=lambda r: EFFECT_RANK[r["effect"]])
    return {"decision": winner["effect"], "reason_code": winner["reason_code"], "reason": winner["reason"], "winning_priority": priority, "matched_rule_ids": [r["id"] for r in winners]}


def validate_tool_schema(schema: dict):
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise GatewayError(422, "INVALID_TOOL_SCHEMA", str(exc)) from exc
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise GatewayError(422, "INVALID_TOOL_SCHEMA", "Tool schema must be an object with additionalProperties=false.")


def validate_arguments(schema: dict, arguments: dict):
    errors = list(Draft202012Validator(schema).iter_errors(arguments))
    if errors:
        raise GatewayError(422, "INVALID_TOOL_ARGUMENTS", errors[0].message)
