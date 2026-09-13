from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ActionRequest, Approval, AuditEvent, ExecutionAttempt, ExecutionJob
from conftest import tool_call


def collect_pages(client, path, headers, params):
    ids = []
    cursor = None
    while True:
        response = client.get(path, headers=headers, params={**params, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()
        ids.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            return ids


def test_audit_events_use_stable_descending_keyset_pagination(client, admin_headers):
    newer = datetime(2030, 1, 2, tzinfo=timezone.utc)
    older = newer - timedelta(days=1)
    with SessionLocal() as db:
        events = [
            AuditEvent(id=f"00000000-0000-0000-0000-0000000009{number:02d}",
                       event_type="PAGINATION_TEST", actor_type="SYSTEM", details={},
                       created_at=newer if number < 3 else older)
            for number in range(5)
        ]
        db.add_all(events)
        db.commit()
        expected = [event.id for event in sorted(events, key=lambda event: (event.created_at, event.id), reverse=True)]

    actual = collect_pages(client, "/api/v1/audit-events", admin_headers,
                           {"event_type": "PAGINATION_TEST", "limit": 2})
    assert actual == expected
    assert len(actual) == len(set(actual)) == 5


def test_approvals_use_stable_descending_keyset_pagination(client, agent_headers, admin_headers):
    created = []
    for number in range(5):
        response = client.post("/api/v1/tool-calls",
            headers={**agent_headers, "Idempotency-Key": f"approval-pagination-{number}"},
            json=tool_call("customers.update", {
                "customer_id": "00000000-0000-0000-0000-000000000020", "status": "SUSPENDED",
            }))
        created.append(response.json()["approval_id"])

    newer = datetime(2030, 1, 2, tzinfo=timezone.utc)
    older = newer - timedelta(days=1)
    with SessionLocal() as db:
        approvals = [db.get(Approval, approval_id) for approval_id in created]
        for number, approval in enumerate(approvals):
            approval.created_at = newer if number < 3 else older
        db.commit()
        expected = [approval.id for approval in sorted(
            approvals, key=lambda approval: (approval.created_at, approval.id), reverse=True)]

    actual = collect_pages(client, "/api/v1/approvals", admin_headers,
                           {"after": "2029-01-01T00:00:00Z", "limit": 2})
    assert actual == expected
    assert len(actual) == len(set(actual)) == 5


def test_seeded_security_story_is_relationally_consistent(client):
    with SessionLocal() as db:
        requests = {request.id: request for request in db.scalars(select(ActionRequest)).all()}
        assert requests["00000000-0000-0000-0000-000000000100"].status == "SUCCEEDED"
        assert requests["00000000-0000-0000-0000-000000000101"].status == "DENIED"
        assert requests["00000000-0000-0000-0000-000000000102"].reason_code == "PROMPT_INJECTION_EXTERNAL_ACTION"

        success_job = db.get(ExecutionJob, "00000000-0000-0000-0000-000000000100")
        success_attempt = db.scalar(select(ExecutionAttempt).where(
            ExecutionAttempt.request_id == success_job.request_id))
        assert (success_job.status, success_job.attempt_count, success_attempt.status) == (
            "SUCCEEDED", 1, "SUCCEEDED")

        pending = db.scalar(select(Approval).where(
            Approval.request_id == "00000000-0000-0000-0000-000000000103"))
        rejected = db.scalar(select(Approval).where(
            Approval.request_id == "00000000-0000-0000-0000-000000000104"))
        rejected_job = db.get(ExecutionJob, rejected.request_id)
        assert pending.status == "PENDING"
        assert pending.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(days=6)
        assert (rejected.status, rejected_job.status, rejected_job.last_error) == (
            "REJECTED", "CANCELLED", "APPROVAL_REJECTED")

        event_types = {event.event_type for event in db.scalars(select(AuditEvent)).all()}
        assert {"AUTHORIZATION_FAILED", "LLM_PROVIDER_UNAVAILABLE", "POLICY_REPLAYED"} <= event_types
        replay = db.get(AuditEvent, "00000000-0000-0000-0000-000000000310")
        assert replay.details["execution_performed"] is False
