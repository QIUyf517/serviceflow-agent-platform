from app.config import Settings
from app.llm import ModelReply, ModelToolCall
from app.main import app, get_service
from fastapi.testclient import TestClient


def test_http_flow(service):
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        headers = {"x-session-id": sid}
        assert client.get("/api/v1/orders/o", headers=headers).status_code == 403
        assert (
            client.post(
                f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/orders/o", headers=headers).json()["status"] == "pending"
        assert client.get("/api/v1/orders/missing", headers=headers).status_code == 404
        p = client.post(
            "/api/v1/operations",
            headers=headers,
            json={"kind": "cancel", "order_id": "o", "reason": "no longer needed"},
        ).json()
        assert (
            client.post(
                f"/api/v1/operations/{p['proposal_id']}/confirm",
                headers=headers,
                json={"confirmed": False},
            ).status_code
            == 400
        )
        assert client.get("/api/v1/orders/o", headers=headers).json()["status"] == "pending"
        assert (
            client.post(
                f"/api/v1/operations/{p['proposal_id']}/confirm",
                headers=headers,
                json={"confirmed": True},
            ).json()["order_status"]
            == "cancelled"
        )
        chat_result = client.post(
            "/api/v1/chat", headers=headers, json={"message": "show order o"}
        ).json()
        trace_path = f"/api/v1/traces/{chat_result['trace_id']}"
        assert client.get(trace_path, headers=headers).status_code == 200
        another = client.post("/api/v1/sessions").json()["session_id"]
        assert client.get(trace_path, headers={"x-session-id": another}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_real_provider_api_route_with_scripted_tool_calls(service, monkeypatch):
    import app.main as api

    replies = iter(
        [
            ModelReply(tool_calls=[ModelToolCall(
                id="tool_1", name="get_order_details", arguments={"order_id": "o"}
            )]),
            ModelReply(content="Your order is pending."),
        ]
    )

    class ScriptedProvider:
        def __init__(self, _settings):
            pass

        def complete(self, _messages, _tools):
            return next(replies)

    monkeypatch.setattr(api, "Settings", lambda: Settings(agent_provider="openai_compatible"))
    monkeypatch.setattr(api, "OpenAICompatibleProvider", ScriptedProvider)
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        assert client.post(
            f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"}
        ).status_code == 200
        headers = {"x-session-id": sid}
        answer = client.post(
            "/api/v1/chat", headers=headers, json={"message": "Check my order o"}
        )
        assert answer.status_code == 200
        assert answer.json()["response"]["message"] == "Your order is pending."
        trace_id = answer.json()["trace_id"]
        trace = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()
        assert any(event.get("name") == "get_order_details" for event in trace["events"])
    finally:
        app.dependency_overrides.clear()
