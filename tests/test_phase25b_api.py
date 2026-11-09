from app.config import Settings
from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient


def configured_client(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    monkeypatch.setattr(api, "Settings", lambda: Settings(_env_file=None, agent_provider="mock"))
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


def create_plan_and_request(client, sid, *, key="api-idem-cancel-0001"):
    plan = client.post(
        "/api/v1/debug/plan",
        headers={"x-session-id": sid},
        json={"message": "帮我取消订单o because ordered by mistake"},
    )
    assert plan.status_code == 200
    proposal = plan.json()["resolution_proposal"]
    created = client.post(
        "/api/v1/multi-agent/cancel-requests",
        headers={"x-session-id": sid},
        json={"proposal_id": proposal["proposal_id"], "idempotency_key": key},
    )
    assert created.status_code == 200
    return created.json()


def test_api_full_cancel_confirmation_execution_and_audit(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        request = create_plan_and_request(client, sid)
        assert request["status"] == "pending_confirmation"
        assert "Cancel order o" in request["summary"]

        pending = client.get(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}",
            headers={"x-session-id": sid},
        )
        assert pending.status_code == 200
        assert pending.json()["confirmation_text"] == request["confirmation_text"]

        decision = client.post(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}/decisions",
            headers={"x-session-id": sid},
            json={
                "decision": "confirm",
                "confirmation_text": request["confirmation_text"],
            },
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "valid"

        executed = client.post(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}/execute",
            headers={
                "x-session-id": sid,
                "Idempotency-Key": request["idempotency_key"],
            },
        )
        assert executed.status_code == 200
        body = executed.json()
        assert body["task_status"] == "executed"
        assert body["execution_result"]["after_status"] == "cancelled"
        assert [event["node"] for event in body["trace"]] == [
            "confirmation",
            "execution",
            "supervisor_result",
            "terminal",
        ]
        assert body["tool_results"] == [
            {"tool": "confirmation_gate", "status": "ok", "code": None},
            {"tool": "execute_cancel_controlled", "status": "ok", "code": None},
        ]

        order = client.get(
            "/api/v1/orders/o", headers={"x-session-id": sid}
        ).json()
        assert order["status"] == "cancelled"
        audit = client.get(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}/audit",
            headers={"x-session-id": sid},
        ).json()["events"]
        assert {event["event_type"] for event in audit} == {
            "proposal_generated",
            "eligibility_validated",
            "user_confirmed",
            "execution_succeeded",
        }
    finally:
        app.dependency_overrides.clear()


def test_api_unconfirmed_request_cannot_execute_or_change_order(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        request = create_plan_and_request(
            client, sid, key="api-idem-unconfirmed-01"
        )
        denied = client.post(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}/execute",
            headers={
                "x-session-id": sid,
                "Idempotency-Key": request["idempotency_key"],
            },
        )
        assert denied.status_code == 409
        assert denied.json() == {"error": {"code": "confirmation_required"}}
        assert client.get(
            "/api/v1/orders/o", headers={"x-session-id": sid}
        ).json()["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_api_rejects_boolean_confirmation_payload(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        request = create_plan_and_request(
            client, sid, key="api-idem-no-boolean-01"
        )
        response = client.post(
            f"/api/v1/multi-agent/cancel-requests/{request['request_id']}/decisions",
            headers={"x-session-id": sid},
            json={"confirmed": True},
        )
        assert response.status_code == 422
        assert client.get(
            "/api/v1/orders/o", headers={"x-session-id": sid}
        ).json()["status"] == "pending"
    finally:
        app.dependency_overrides.clear()
