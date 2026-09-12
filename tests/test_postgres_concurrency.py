"""Concurrency checks that run only with an explicitly supplied PostgreSQL test DB.

Example: TEST_DATABASE_URL=postgresql+psycopg://... python -m pytest -q
Never point this suite at a database containing data: the autouse fixture recreates tables.
"""
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app.db import engine
from app.db import SessionLocal
from app.main import app
from app.models import ActionRequest, ExecutionJob, UsageBucket
from app.worker import claim_job
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


@postgres_only
def test_concurrent_identical_idempotent_requests_share_one_record(client, agent_headers):
    def submit(_):
        with TestClient(app) as concurrent_client:
            response = concurrent_client.post("/api/v1/tool-calls",
                headers={**agent_headers, "Idempotency-Key": "pg-identical"}, json=tool_call())
            return response.status_code, response.json()["request_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["a", "b"]))
    assert [status for status, _ in results] == [200, 200]
    assert len({request_id for _, request_id in results}) == 1
    with SessionLocal() as db:
        assert len(db.query(ActionRequest).filter_by(idempotency_key="pg-identical").all()) == 1
        assert len(db.query(ExecutionJob).all()) == 1
        assert db.query(UsageBucket).one().used_requests == 1


@postgres_only
def test_concurrent_different_payloads_with_same_key_conflict(client, agent_headers):
    def submit(query):
        with TestClient(app) as concurrent_client:
            response = concurrent_client.post("/api/v1/tool-calls",
                headers={**agent_headers, "Idempotency-Key": "pg-conflicting"},
                json=tool_call(arguments={"query": query}))
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["Customer", "Other"]))
    assert sorted(status for status, _ in results) == [200, 409]
    assert next(body for status, body in results if status == 409)["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    with SessionLocal() as db:
        assert len(db.query(ActionRequest).filter_by(idempotency_key="pg-conflicting").all()) == 1
        assert db.query(UsageBucket).one().used_requests == 1


@postgres_only
def test_concurrent_duplicate_approval_creates_exactly_one_job(client, agent_headers, admin_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "pg-double-approve"},
        json=tool_call("customers.update", {"customer_id": "00000000-0000-0000-0000-000000000020", "status": "SUSPENDED"})).json()

    def approve(note):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(f"/api/v1/approvals/{created['approval_id']}/approve",
                headers=admin_headers, json={"note": note}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(approve, ["one", "two"]))
    assert statuses == [200, 409]
    with SessionLocal() as db:
        assert len(db.query(ExecutionJob).all()) == 1


@postgres_only
def test_concurrent_workers_claim_job_once(client, agent_headers):
    created = client.post("/api/v1/tool-calls", headers={**agent_headers, "Idempotency-Key": "pg-job-claim"}, json=tool_call()).json()

    def claim(worker_id):
        with SessionLocal() as db:
            return claim_job(db, worker_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ["worker-one", "worker-two"]))
    assert sorted(claim is None for claim in claims) == [False, True]
    assert created["request_id"] in claims
    with SessionLocal() as db:
        job = db.get(ExecutionJob, created["request_id"])
        assert job.status == "RUNNING"
        assert job.attempt_count == 1
