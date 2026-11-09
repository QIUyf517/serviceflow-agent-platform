from copy import deepcopy

from app.config import Settings
from app.database import OrderRow, UserRow
from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_debug_api_exposes_resolution_validation_and_full_trace(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    monkeypatch.setattr(api, "Settings", lambda: Settings(_env_file=None, agent_provider="mock"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        response = client.post(
            "/api/v1/debug/plan",
            headers={"x-session-id": sid},
            json={"message": "帮我取消订单o because ordered by mistake"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["input"].startswith("帮我取消")
        assert data["triage"]["intent"] == "cancel_order"
        assert data["order_data"]["order-lookup"]["source"] == "business_database"
        assert data["policy_context"]
        assert data["resolution_proposal"]["status"] == "pending_confirmation"
        assert data["eligibility_result"]["validated"] is True
        assert data["pending_action"]["proposal_id"].startswith("resolution_")
        assert data["final_response"].endswith("No business change was made.")
        assert [event["node"] for event in data["full_trace"]][-3:] == [
            "guard",
            "supervisor_result",
            "terminal",
        ]
        assert service.order(sid, "o")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_keyword_return_flow_matches_real_policy_and_rules(service):
    import app.main as api

    with Session(service.engine) as db, db.begin():
        row = db.get(OrderRow, "o")
        order = deepcopy(row.order_json)
        order["status"] = "delivered"
        order["payment_history"] = [
            {
                "transaction_type": "payment",
                "amount": 10.0,
                "payment_method_id": "card",
            }
        ]
        row.order_json = order
        row.status = "delivered"
        user = db.get(UserRow, "u")
        profile = deepcopy(user.profile_json)
        profile["payment_methods"] = {"card": {"source": "credit_card"}}
        user.profile_json = profile

    api.phase22_store = SessionStateStore()
    app.dependency_overrides[get_service] = lambda: service
    original_settings = api.Settings
    api.Settings = lambda: Settings(_env_file=None, agent_provider="mock")
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        data = client.post(
            "/api/v1/debug/plan",
            headers={"x-session-id": sid},
            json={
                "message": (
                    "我要退货订单o item_ids=i payment_method_id=card，"
                    "请按退货政策处理"
                )
            },
        ).json()
        assert data["policy_retrieval"]["method"] == "keyword"
        assert any(
            evidence["section"] == "Return delivered order"
            for evidence in data["policy_context"]
        )
        assert data["resolution_proposal"]["action_type"] == "return"
        assert data["eligibility_result"]["status"] == "eligible"
        assert service.order(sid, "o")["status"] == "delivered"
    finally:
        api.Settings = original_settings
        app.dependency_overrides.clear()
