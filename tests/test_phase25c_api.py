from copy import deepcopy

from app.agent import chat_once
from app.database import OrderRow
from app.main import app, get_execution_service, get_service
from app.multi_agent.execution import ExecutionService
from app.multi_agent.workflow import SessionStateStore
from app.service import Action
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def configured_client(service, monkeypatch, execution=None):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    app.dependency_overrides[get_service] = lambda: service
    if execution is not None:
        app.dependency_overrides[get_execution_service] = lambda: execution
    return TestClient(app)


def verified_session(client, email="test@example.invalid"):
    sid = client.post("/api/v1/sessions").json()["session_id"]
    verified = client.post(f"/api/v1/sessions/{sid}/verify", json={"email": email})
    assert verified.status_code == 200
    return sid


def start_cancel(client, sid):
    response = client.post(
        "/api/v1/multi-agent/chat",
        headers={"x-session-id": sid},
        json={
            "message": "Please cancel order o because ordered by mistake",
            "order_id": "o",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_status"] == "pending_confirmation"
    assert body["resolution_proposal"]["action_type"] == "cancel"
    assert body["eligibility_result"]["status"] == "eligible"
    assert body["eligibility_result"]["validated"] is True
    assert body["eligibility_result"]["checked_order_status"] == "pending"
    assert body["pending_confirmation"]["confirmation_text"].startswith(
        "confirm cancel_order order=o"
    )
    return body


def test_natural_language_two_turn_cancel_and_idempotent_resume(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = start_cancel(client, sid)
        request_id = waiting["request_id"]
        assert (
            client.get("/api/v1/orders/o", headers={"x-session-id": sid}).json()["status"]
            == "pending"
        )

        progress = client.get(
            "/api/v1/multi-agent/tasks/current",
            headers={"x-session-id": sid},
            params={"order_id": "o"},
        )
        assert progress.status_code == 200
        assert progress.json()["pending_confirmation"]["request_id"] == request_id
        assert progress.json()["policy_context"]
        assert all(
            item["source"].endswith("policy.md") for item in progress.json()["policy_context"]
        )

        confirmed = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "确认", "request_id": request_id, "order_id": "o"},
        )
        assert confirmed.status_code == 200
        result = confirmed.json()
        assert result["task_status"] == "executed"
        assert result["execution_result"]["after_status"] == "cancelled"
        assert [event["node"] for event in result["trace"]] == [
            "content_safety",
            "confirmation",
            "execution",
            "supervisor_result",
            "terminal",
        ]
        assert (
            client.get("/api/v1/orders/o", headers={"x-session-id": sid}).json()["status"]
            == "cancelled"
        )

        replay = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "确认", "request_id": request_id, "order_id": "o"},
        )
        assert replay.status_code == 200
        assert replay.json()["execution_result"]["idempotent_replay"] is True
        assert replay.json()["execution_result"]["row_version"] == 2
        audit = client.get(
            f"/api/v1/multi-agent/cancel-requests/{request_id}/audit",
            headers={"x-session-id": sid},
        ).json()["events"]
        assert [event["event_type"] for event in audit].count("execution_succeeded") == 1
    finally:
        app.dependency_overrides.clear()


def test_reject_and_changed_intent_never_execute_old_request(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = start_cancel(client, sid)
        request_id = waiting["request_id"]
        rejected = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "拒绝", "request_id": request_id, "order_id": "o"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["task_status"] == "confirmation_rejected"
        assert service.order(sid, "o")["status"] == "pending"

        second = start_cancel(client, sid)
        old_id = second["request_id"]
        changed_order = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={
                "message": "Please cancel order other because ordered by mistake",
                "request_id": old_id,
                "order_id": "o",
            },
        )
        assert changed_order.status_code == 200
        assert changed_order.json()["task_status"] == "order_scope_mismatch"
        assert (
            client.get(
                f"/api/v1/multi-agent/cancel-requests/{old_id}",
                headers={"x-session-id": sid},
            ).json()["status"]
            == "superseded"
        )

        third = start_cancel(client, sid)
        old_id = third["request_id"]
        changed = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={
                "message": "Please show order o status",
                "request_id": old_id,
                "order_id": "o",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["task_status"] == "queried"
        persisted = client.get(
            f"/api/v1/multi-agent/cancel-requests/{old_id}",
            headers={"x-session-id": sid},
        ).json()
        assert persisted["status"] == "superseded"
        old_execute = client.post(
            f"/api/v1/multi-agent/cancel-requests/{old_id}/execute",
            headers={
                "x-session-id": sid,
                "Idempotency-Key": persisted["idempotency_key"],
            },
        )
        assert old_execute.status_code == 409
        assert old_execute.json()["error"]["code"] == "execution_request_superseded"
        assert service.order(sid, "o")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_expired_confirmation_and_changed_order_fail_closed(service, monkeypatch):
    now = [1_000]
    execution = ExecutionService(service.engine, confirmation_ttl_seconds=1, clock=lambda: now[0])
    client = configured_client(service, monkeypatch, execution)
    try:
        sid = verified_session(client)
        waiting = start_cancel(client, sid)
        now[0] = 1_002
        expired = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={
                "message": "确认",
                "request_id": waiting["request_id"],
                "order_id": "o",
            },
        )
        assert expired.status_code == 200
        assert expired.json()["task_status"] == "execution_failed"
        assert expired.json()["failure_reason"] == "confirmation_expired"
        assert expired.json()["ticket"] is None
        assert "智能客服当前无法解决" in expired.json()["final_response"]
        assert "如需人工客服" in expired.json()["final_response"]
        assert service.order(sid, "o")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()

    client = configured_client(service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = start_cancel(client, sid)
        with Session(service.engine) as db, db.begin():
            row = db.get(OrderRow, "o")
            payload = deepcopy(row.order_json)
            payload["status"] = "processed"
            row.order_json = payload
            row.status = "processed"
            row.row_version += 1
        changed = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={
                "message": "确认",
                "request_id": waiting["request_id"],
                "order_id": "o",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["task_status"] == "execution_failed"
        assert changed.json()["failure_reason"] == "order_changed"
        assert changed.json()["ticket"] is None
        assert "智能客服当前无法解决" in changed.json()["final_response"]
        assert "如需人工客服" in changed.json()["final_response"]
        assert service.order(sid, "o")["status"] == "processed"
    finally:
        app.dependency_overrides.clear()


def test_session_isolation_and_unverified_identity(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = start_cancel(client, sid)
        other = verified_session(client, "v@example.invalid")
        stolen = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": other},
            json={"message": "确认", "request_id": waiting["request_id"]},
        )
        assert stolen.status_code == 404
        assert stolen.json()["error"]["code"] == "execution_request_not_found"

        anonymous = client.post("/api/v1/sessions").json()["session_id"]
        unauthenticated = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": anonymous},
            json={"message": "Please cancel order o because ordered by mistake"},
        )
        assert unauthenticated.status_code == 200
        assert unauthenticated.json()["task_status"] == "order_thread_required"
        assert unauthenticated.json()["request_id"] is None
        assert service.order(sid, "o")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_legacy_http_write_paths_are_gone_but_baseline_reads_remain(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = verified_session(client)
        legacy = service.propose(
            sid, Action(kind="cancel", order_id="o", reason="no longer needed")
        )
        confirm = client.post(
            f"/api/v1/operations/{legacy['proposal_id']}/confirm",
            headers={"x-session-id": sid},
            json={"confirmed": True},
        )
        assert confirm.status_code == 410
        chat_confirm = client.post(
            "/api/v1/chat",
            headers={"x-session-id": sid},
            json={"message": "yes", "proposal_id": legacy["proposal_id"]},
        )
        assert chat_confirm.status_code == 410
        assert service.order(sid, "o")["status"] == "pending"

        baseline = chat_once(service, sid, "show order o")
        assert baseline["response"]["order"]["order_id"] == "o"
    finally:
        app.dependency_overrides.clear()
