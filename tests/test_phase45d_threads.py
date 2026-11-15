"""Phase 4.5D: server-side order threads keep one customer's orders apart."""

from copy import deepcopy

import pytest
from app.database import engine_for, seed
from app.main import app, get_service, get_ticket_service
from app.multi_agent.workflow import SessionStateStore
from app.retail import validate
from app.service import RetailService
from app.ticketing import TicketService
from fastapi.testclient import TestClient

OPERATOR_TOKEN = "phase45d-local-operator-token"


def _address() -> dict:
    return {
        "address1": "test",
        "address2": "",
        "city": "test",
        "country": "test",
        "state": "test",
        "zip": "00000",
    }


def _sample() -> dict:
    address = _address()

    def order(order_id: str) -> dict:
        return {
            "order_id": order_id,
            "user_id": "u",
            "status": "pending",
            "address": address,
            "items": [
                {
                    "item_id": "i",
                    "product_id": "p",
                    "name": "Test product",
                    "options": {},
                    "price": 10.0,
                }
            ],
            "fulfillments": [],
            "payment_history": [],
        }

    users = {
        "u": {
            "user_id": "u",
            "name": {"first_name": "Test", "last_name": "User"},
            "email": "test@example.invalid",
            "address": address,
            "payment_methods": {},
            "orders": ["o", "o2"],
        },
        "v": {
            "user_id": "v",
            "name": {"first_name": "Other", "last_name": "User"},
            "email": "v@example.invalid",
            "address": address,
            "payment_methods": {},
            "orders": [],
        },
    }
    products = {
        "p": {
            "product_id": "p",
            "name": "Test product",
            "variants": {
                "i": {"item_id": "i", "options": {}, "available": True, "price": 12.0}
            },
        }
    }
    return deepcopy(
        {"users": users, "products": products, "orders": {"o": order("o"), "o2": order("o2")}}
    )


@pytest.fixture
def two_order_service(tmp_path):
    engine = engine_for(f"sqlite:///{(tmp_path / 'threads.db').as_posix()}", testing=True)
    seed(engine, validate(_sample()), "test")
    service = RetailService(engine)
    yield service
    engine.dispose()


def configured_client(service, monkeypatch):
    import app.main as api

    monkeypatch.setenv("OPERATOR_DEMO_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setenv("OPERATOR_DEMO_ID", "operator-test")
    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_ticket_service] = lambda: TicketService(service.engine)
    return TestClient(app)


def operator_headers() -> dict[str, str]:
    return {"x-operator-token": OPERATOR_TOKEN}


def verified_session(client, email: str = "test@example.invalid") -> str:
    sid = client.post("/api/v1/sessions").json()["session_id"]
    assert client.post(f"/api/v1/sessions/{sid}/verify", json={"email": email}).status_code == 200
    return sid


def open_thread(client, sid: str, order_id: str | None = None) -> dict:
    body = {"order_id": order_id} if order_id else {}
    response = client.post(
        "/api/v1/support/threads", headers={"x-session-id": sid}, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def chat(client, sid: str, message: str, **fields):
    return client.post(
        "/api/v1/multi-agent/chat",
        headers={"x-session-id": sid},
        json={"message": message, **fields},
    )


def conversation(client, sid: str, order_id: str | None = None) -> list[dict]:
    params = {"order_id": order_id} if order_id else {}
    response = client.get(
        "/api/v1/customer/conversation", headers={"x-session-id": sid}, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_two_orders_get_distinct_threads_and_isolated_messages(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        thread_a = open_thread(client, sid, "o")
        thread_b = open_thread(client, sid, "o2")
        assert thread_a["thread_id"] != thread_b["thread_id"]
        assert thread_a["kind"] == "order"
        assert thread_a["order_id"] == "o"
        assert thread_b["order_id"] == "o2"
        assert open_thread(client, sid, "o")["thread_id"] == thread_a["thread_id"]

        product = chat(client, sid, "商品 p 现在多少钱", order_id="o")
        policy = chat(client, sid, "退货需要什么条件？", order_id="o2")
        assert product.status_code == 200 and policy.status_code == 200
        assert product.json()["thread_id"] == thread_a["thread_id"]
        assert product.json()["thread_order_id"] == "o"
        assert policy.json()["thread_id"] == thread_b["thread_id"]

        order_a = conversation(client, sid, "o")
        order_b = conversation(client, sid, "o2")
        assert order_a and order_b
        assert all(item["thread_id"] == thread_a["thread_id"] for item in order_a)
        assert all(item["thread_id"] == thread_b["thread_id"] for item in order_b)
        assert any("商品 p" in item["content"] for item in order_a)
        assert all("退货需要什么条件" not in item["content"] for item in order_a)
        assert any("退货需要什么条件" in item["content"] for item in order_b)
        assert all("商品 p" not in item["content"] for item in order_b)
    finally:
        app.dependency_overrides.clear()


def test_operator_console_and_customer_window_share_one_order_thread(
    two_order_service, monkeypatch
):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        handoff = chat(client, sid, "请帮我转人工客服", order_id="o")
        assert handoff.status_code == 200
        handoff_body = handoff.json()
        assert handoff_body["task_status"] == "handoff_created"
        ticket = handoff_body["ticket"]
        assert ticket["order_id"] == "o"
        assert ticket["thread_id"] == handoff_body["thread_id"]

        chat(client, sid, "商品 p 现在多少钱", order_id="o2")

        detail = client.get(
            f"/api/v1/tickets/{ticket['id']}", headers=operator_headers()
        ).json()
        assert detail["thread"]["thread_id"] == ticket["thread_id"]
        assert detail["thread"]["order_id"] == "o"
        contents = [message["content"] for message in detail["conversation"]]
        assert any("请帮我转人工客服" in content for content in contents)
        assert all("商品 p 现在多少钱" not in content for content in contents)

        reply = client.post(
            f"/api/v1/tickets/{ticket['id']}/reply",
            headers=operator_headers(),
            json={"content": "我来帮您核实这笔订单。"},
        )
        assert reply.status_code == 200

        order_a = conversation(client, sid, "o")
        order_b = conversation(client, sid, "o2")
        assert any(
            item["role"] == "operator" and item["content"] == "我来帮您核实这笔订单。"
            for item in order_a
        )
        assert all(item["role"] != "operator" for item in order_b)

        restored = client.get(
            f"/api/v1/tickets/{ticket['id']}", headers=operator_headers()
        ).json()
        assert restored["thread"]["thread_id"] == detail["thread"]["thread_id"]
        assert [message["sequence"] for message in restored["conversation"]] == [
            message["sequence"] for message in detail["conversation"]
        ] + [restored["conversation"][-1]["sequence"]]
    finally:
        app.dependency_overrides.clear()


def test_general_consultation_never_enters_an_order_thread(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        general = open_thread(client, sid)
        order_thread = open_thread(client, sid, "o")
        assert general["thread_id"] != order_thread["thread_id"]
        assert general["kind"] == "general" and general["order_id"] is None

        assert chat(client, sid, "退货需要什么条件？").status_code == 200
        assert chat(client, sid, "商品 p 现在多少钱", order_id="o").status_code == 200

        general_messages = conversation(client, sid)
        order_messages = conversation(client, sid, "o")
        assert all(item["thread_id"] == general["thread_id"] for item in general_messages)
        assert any("退货需要什么条件" in item["content"] for item in general_messages)
        assert all("退货需要什么条件" not in item["content"] for item in order_messages)

        ticket = client.post(
            "/api/v1/tickets",
            headers={"x-session-id": sid, "Idempotency-Key": "phase45d-general-ticket-0001"},
            json={
                "summary": "顾客在通用咨询中明确要求人工。",
                "requested_action": {"source": "web_user_page"},
            },
        ).json()
        assert ticket["order_id"] is None
        assert ticket["thread_id"] == general["thread_id"]
    finally:
        app.dependency_overrides.clear()


def test_cross_customer_thread_access_is_rejected(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        other = verified_session(client, "v@example.invalid")
        assert chat(client, sid, "商品 p 现在多少钱", order_id="o").status_code == 200

        assert (
            client.post(
                "/api/v1/support/threads",
                headers={"x-session-id": other},
                json={"order_id": "o"},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/customer/conversation",
                headers={"x-session-id": other},
                params={"order_id": "o"},
            ).status_code
            == 404
        )
        assert chat(client, other, "商品 p 现在多少钱", order_id="o").status_code == 404
        assert (
            client.get(
                "/api/v1/multi-agent/tasks/current",
                headers={"x-session-id": other},
                params={"order_id": "o"},
            ).status_code
            == 404
        )
        assert conversation(client, other) == []
    finally:
        app.dependency_overrides.clear()


def test_switching_threads_does_not_carry_a_pending_confirmation(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = chat(client, sid, "取消订单，因为误下单", order_id="o")
        assert waiting.status_code == 200
        waiting_body = waiting.json()
        assert waiting_body["task_status"] == "pending_confirmation"
        assert waiting_body["thread_order_id"] == "o"
        request_id = waiting_body["request_id"]

        pending = client.get(
            "/api/v1/multi-agent/tasks/current",
            headers={"x-session-id": sid},
            params={"order_id": "o"},
        )
        assert pending.status_code == 200
        assert pending.json()["pending_confirmation"]["request_id"] == request_id
        assert (
            client.get(
                "/api/v1/multi-agent/tasks/current",
                headers={"x-session-id": sid},
                params={"order_id": "o2"},
            ).status_code
            == 404
        )

        cross = chat(client, sid, "确认", order_id="o2").json()
        assert cross["task_status"] != "executed"
        assert cross["execution_result"] is None
        assert cross["pending_confirmation"] is None
        assert two_order_service.order(sid, "o")["status"] == "pending"
        assert two_order_service.order(sid, "o2")["status"] == "pending"

        confirmed = chat(
            client, sid, "确认", order_id="o", request_id=request_id
        ).json()
        assert confirmed["task_status"] == "executed"
        assert confirmed["execution_result"]["after_status"] == "cancelled"
        assert two_order_service.order(sid, "o")["status"] == "cancelled"
        assert two_order_service.order(sid, "o2")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_order_thread_refuses_messages_about_another_order(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        response = chat(client, sid, "帮我取消订单 o2，因为误下单", order_id="o")
        assert response.status_code == 200
        body = response.json()
        assert body["task_status"] == "order_scope_mismatch"
        assert "o2" not in body["final_response"] or "绑定订单 o" in body["final_response"]
        assert body["pending_confirmation"] is None
        assert two_order_service.order(sid, "o2")["status"] == "pending"
        assert two_order_service.order(sid, "o")["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_operator_reply_never_substitutes_customer_confirmation(two_order_service, monkeypatch):
    client = configured_client(two_order_service, monkeypatch)
    try:
        sid = verified_session(client)
        waiting = chat(client, sid, "取消订单，因为误下单", order_id="o").json()
        assert waiting["task_status"] == "pending_confirmation"
        ticket = client.post(
            "/api/v1/tickets",
            headers={
                "x-session-id": sid,
                "Idempotency-Key": "phase45d-human-ticket-0002",
            },
            json={
                "summary": "顾客在取消方案待确认时要求人工。",
                "order_id": "o",
                "request_id": waiting["request_id"],
                "thread_id": waiting["thread_id"],
            },
        ).json()
        assert ticket["order_id"] == "o"
        assert ticket["thread_id"] == waiting["thread_id"]

        reply = client.post(
            f"/api/v1/tickets/{ticket['id']}/reply",
            headers=operator_headers(),
            json={"content": "我来帮您处理这笔取消。"},
        )
        assert reply.status_code == 200
        assert two_order_service.order(sid, "o")["status"] == "pending"

        detail = client.get(
            f"/api/v1/tickets/{ticket['id']}", headers=operator_headers()
        ).json()
        assert detail["request"]["status"] == "pending_confirmation"

        approved = client.post(
            f"/api/v1/tickets/{ticket['id']}/approvals",
            headers=operator_headers(),
            json={"action": "execute_cancel", "proposed_params": {}},
        )
        assert approved.status_code == 200
        decided = client.post(
            f"/api/v1/tickets/{ticket['id']}/approvals/{approved.json()['id']}/decision",
            headers=operator_headers(),
            json={"decision": "approved", "reason": "内部复核通过"},
        )
        assert decided.status_code == 200
        assert two_order_service.order(sid, "o")["status"] == "pending"

        confirmed = chat(
            client, sid, "确认", order_id="o", request_id=waiting["request_id"]
        ).json()
        assert confirmed["task_status"] == "executed"
        assert two_order_service.order(sid, "o")["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()
