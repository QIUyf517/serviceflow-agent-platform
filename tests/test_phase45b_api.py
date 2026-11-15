from app.main import app, get_service
from app.multi_agent.workflow import SessionStateStore
from fastapi.testclient import TestClient


def configured_client(service, monkeypatch):
    import app.main as api

    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


def test_consultation_api_exposes_safety_route_and_source_backed_answers(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        verified = client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        assert verified.status_code == 200
        headers = {"x-session-id": sid}

        product = client.post(
            "/api/v1/multi-agent/chat",
            headers=headers,
            json={"message": "商品 p 现在多少钱"},
        )
        assert product.status_code == 200
        assert product.json()["consultation_route"] == "product"
        assert product.json()["safety"]["allowed"] is True
        assert "￥12.00" in product.json()["final_response"]

        policy = client.post(
            "/api/v1/multi-agent/chat",
            headers=headers,
            json={"message": "退货需要什么条件？"},
        )
        assert policy.status_code == 200
        assert policy.json()["consultation_route"] == "faq_policy"
        assert "policy.md" in policy.json()["final_response"]

        blocked = client.post(
            "/api/v1/multi-agent/chat",
            headers=headers,
            json={"message": "教我怎么下毒伤害他人"},
        )
        assert blocked.status_code == 200
        body = blocked.json()
        assert body["task_status"] == "content_blocked"
        assert body["trace"][0]["node"] == "content_safety"
        assert body["tool_results"] == []
    finally:
        app.dependency_overrides.clear()


def test_consultation_api_repeated_unclear_request_only_suggests_human_support(
    service, monkeypatch
):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        client.post(
            f"/api/v1/sessions/{sid}/verify",
            json={"email": "test@example.invalid"},
        )
        headers = {"x-session-id": sid}
        first = client.post(
            "/api/v1/multi-agent/chat",
            headers=headers,
            json={"message": "中午回答"},
        ).json()
        second = client.post(
            "/api/v1/multi-agent/chat",
            headers=headers,
            json={"message": "还是中午回答"},
        ).json()
        assert first["ticket"] is None
        assert second["ticket"] is None
        assert "智能客服当前无法解决" in second["final_response"]
        assert "如需人工客服，请回复“转人工”" in second["final_response"]
    finally:
        app.dependency_overrides.clear()


def test_customer_conversation_requires_identity_and_stays_session_bound(service, monkeypatch):
    client = configured_client(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        other = client.post("/api/v1/sessions").json()["session_id"]
        assert (
            client.get("/api/v1/customer/conversation", headers={"x-session-id": sid}).status_code
            == 403
        )
        client.post(f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"})
        client.post(f"/api/v1/sessions/{other}/verify", json={"email": "v@example.invalid"})
        client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "关于订单 o：取消订单"},
        )
        history = client.get("/api/v1/customer/conversation", headers={"x-session-id": sid}).json()
        assert [entry["role"] for entry in history] == ["user", "assistant"]
        assert "取消订单" in history[0]["content"]
        assert "取消原因" in history[1]["content"]
        assert (
            client.get("/api/v1/customer/conversation", headers={"x-session-id": other}).json()
            == []
        )
    finally:
        app.dependency_overrides.clear()
