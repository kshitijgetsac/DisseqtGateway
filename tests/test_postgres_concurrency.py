"""Concurrency checks that run only with an explicitly supplied PostgreSQL test DB.

Example: TEST_DATABASE_URL=postgresql+psycopg://... python -m pytest -q
Never point this suite at a database containing data: the autouse fixture recreates tables.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import pytest
from fastapi.testclient import TestClient
from app.db import engine
from app.main import app
from conftest import tool_call


postgres_only = pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL row locks required")


@postgres_only
def test_concurrent_approval_only_one_resolver_wins(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "pg-approval"},
        json=tool_call("customers.update", {"customer_id": "00000000-0000-0000-0000-000000000020", "status": "SUSPENDED"})).json()
    approval_id = created["approval_id"]

    def resolve(path):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(f"/api/v1/approvals/{approval_id}/{path}", headers=admin_headers, json={"note": path}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(resolve, ["approve", "reject"]))
    assert statuses == [200, 409]


@postgres_only
def test_concurrent_budget_final_slot_has_one_winner(client, agent_headers, admin_headers):
    client.put("/api/v1/budgets", headers=admin_headers, json={
        "agent_id": "00000000-0000-0000-0000-000000000010", "model": "mock-secure-v1",
        "request_limit": 1, "token_limit": 10000})

    def submit(suffix):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": f"pg-budget-{suffix}"}, json=tool_call()).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(submit, ["a", "b"]))
    assert statuses == [200, 429]
