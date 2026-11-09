from app.config import Settings
from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient


def test_debug_plan_api_is_separate_from_baseline(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    monkeypatch.setattr(api, "Settings", lambda: Settings(_env_file=None, agent_provider="mock"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        headers = {"x-session-id": sid}
        first = client.post("/api/v1/debug/plan", headers=headers, json={"message": "查询订单状态"})
        assert first.status_code == 200
        assert first.json()["task_status"] == "clarification"
        assert set(first.json()["missing_information"]) == {"order_id", "identity_verification"}
        assert (
            client.post(
                f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"}
            ).status_code
            == 200
        )
        second = client.post("/api/v1/debug/plan", headers=headers, json={"message": "o"})
        assert second.status_code == 200
        assert second.json()["triage"]["order_id"] == "o"
        assert second.json()["next_agent"] == "end"
        assert second.json()["task_plan"][0]["status"] == "completed"
        assert second.json()["order_data"]["order-lookup"]["status"] == "pending"
        assert second.json()["trace"][-1]["node"] == "terminal"
        assert (
            client.post(
                "/api/v1/debug/plan", headers={"x-session-id": "missing"}, json={"message": "你好"}
            ).status_code
            == 404
        )
        baseline = client.post("/api/v1/chat", headers=headers, json={"message": "show order o"})
        assert baseline.status_code == 200
        assert baseline.json()["response"]["order"]["status"] == "pending"
    finally:
        app.dependency_overrides.clear()
