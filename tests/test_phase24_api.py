from app.config import Settings
from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient


def test_debug_api_exposes_policy_query_hits_scores_sources_and_state(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    monkeypatch.setattr(api, "Settings", lambda: Settings(_env_file=None, agent_provider="mock"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        response = client.post(
            "/api/v1/debug/plan",
            headers={"x-session-id": sid},
            json={"message": "换货政策是什么？"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["triage"]["intent"] == "policy_inquiry"
        assert data["policy_retrieval"]["query"] == "换货政策是什么？"
        assert data["policy_retrieval"]["method"] == "keyword"
        assert "exchange" in data["policy_retrieval"]["terms"]
        assert data["policy_retrieval"]["hits"][0]["section"] == "Exchange delivered order"
        assert isinstance(data["policy_retrieval"]["hits"][0]["score"], float)
        assert data["policy_context"] == data["state"]["policy_context"]
        assert data["trace"][2]["node"] == "policy"
        assert data["final_response"]
    finally:
        app.dependency_overrides.clear()
