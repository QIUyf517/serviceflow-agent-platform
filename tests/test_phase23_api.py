from app.config import Settings
from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient


def test_order_debug_api_shows_tool_input_result_and_state(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    monkeypatch.setattr(api, "Settings", lambda: Settings(_env_file=None, agent_provider="mock"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        headers = {"x-session-id": sid}
        denied = client.post(
            "/api/v1/debug/plan", headers=headers, json={"message": "查询订单o状态"}
        ).json()
        assert denied["task_status"] == "clarification"
        assert denied["order_data"] == {}
        public = client.post(
            "/api/v1/debug/plan", headers=headers, json={"message": "product p details"}
        ).json()
        assert public["order_data"]["product-lookup"]["product"]["product_id"] == "p"
        assert (
            client.post(
                f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"}
            ).status_code
            == 200
        )
        result = client.post(
            "/api/v1/debug/plan", headers=headers, json={"message": "查询订单o状态"}
        )
        assert result.status_code == 200
        data = result.json()
        assert data["triage"]["intent"] == "order_query"
        assert data["task_plan"][0]["status"] == "completed"
        assert data["order_data"]["order-lookup"]["status"] == "pending"
        assert data["trace"][2]["tool"] == "get_order_status"
        assert data["trace"][2]["arguments"] == {"order_id": "o"}
        assert data["state"]["order_context"] == {"order_id": "o", "status": "pending"}
        assert data["next_agent"] == "end"
        baseline = client.post("/api/v1/chat", headers=headers, json={"message": "show order o"})
        assert baseline.status_code == 200
    finally:
        app.dependency_overrides.clear()
