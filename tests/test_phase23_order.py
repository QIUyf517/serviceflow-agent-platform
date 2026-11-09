from copy import deepcopy

import pytest
from app.database import OrderRow
from app.multi_agent.order_agent import MAX_ORDER_TOOL_CALLS, run_order_agent
from app.multi_agent.order_tools import OrderToolCall, execute_order_tool
from app.multi_agent.state import apply_agent_update, new_agent_state
from app.multi_agent.supervisor import supervise
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_turn
from app.service import BusinessError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def verified(service, email="test@example.invalid"):
    sid = service.start()
    service.verify(sid, email=email)
    return sid


@pytest.mark.parametrize(
    ("message", "kind", "tool"),
    [
        ("查询订单o详情", "order", "get_order_details"),
        ("查询订单o状态", "status", "get_order_status"),
        ("查询订单o中的商品", "items", "get_order_items"),
        ("查询订单o物流", "logistics", "get_order_logistics"),
    ],
)
def test_readonly_order_queries_use_service_and_project_data(service, message, kind, tool):
    sid = verified(service)
    result = run_turn(service, sid, message, MockTriage(), SessionStateStore())
    data = result["order_data"]["order-lookup"]
    assert result["task_status"] == "queried"
    assert data["source"] == "business_database"
    assert data["kind"] == kind
    assert data["order_id"] == "o"
    assert result["order_context"] == {"order_id": "o", "status": "pending"}
    assert result["tool_results"] == [{"tool": tool, "status": "ok", "code": None}]
    assert result["trace"][2]["tool"] == tool
    assert "address" not in str(data) and "payment_history" not in str(data)
    assert "user_id" not in str(data)


def test_order_list_returns_only_own_order_ids(service):
    owner = verified(service)
    other = verified(service, "v@example.invalid")
    first = run_turn(service, owner, "我的订单列表", MockTriage(), SessionStateStore())
    second = run_turn(service, other, "我的订单列表", MockTriage(), SessionStateStore())
    assert first["order_data"]["order-lookup"]["orders"] == [{"order_id": "o", "status": "pending"}]
    assert second["order_data"]["order-lookup"]["orders"] == []


def test_existing_tracking_fields_are_returned_without_invention(service):
    with Session(service.engine) as db, db.begin():
        row = db.get(OrderRow, "o")
        order = deepcopy(row.order_json)
        order["fulfillments"] = [{"item_ids": ["i"], "tracking_id": ["TRACK-1"]}]
        row.order_json = order
    sid = verified(service)
    result = run_turn(service, sid, "查询订单o物流", MockTriage(), SessionStateStore())
    data = result["order_data"]["order-lookup"]
    assert data["fulfillments"] == [{"item_ids": ["i"], "tracking_id": ["TRACK-1"]}]
    assert "delivery_time" not in data


def test_public_product_query_has_distinct_permission_from_private_orders(service):
    sid = service.start()
    product = run_turn(service, sid, "product p details", MockTriage(), SessionStateStore())
    assert product["task_status"] == "queried"
    detail = product["order_data"]["product-lookup"]["product"]
    assert detail["product_id"] == "p"
    assert detail["variants"]["i"]["price"] == 12.0
    assert detail["variants"]["i"]["available"] is True
    with pytest.raises(BusinessError, match="identity_required"):
        service.product(sid, "p")
    denied = run_turn(service, sid, "查询订单o详情", MockTriage(), SessionStateStore())
    assert denied["task_status"] == "clarification"
    assert denied["order_data"] == {}


def test_missing_and_foreign_orders_share_safe_error(service):
    sid = verified(service, "v@example.invalid")
    foreign = run_turn(service, sid, "查询订单o详情", MockTriage(), SessionStateStore())
    missing = run_turn(service, sid, "查询订单missing详情", MockTriage(), SessionStateStore())
    for result in (foreign, missing):
        assert result["task_status"] == "query_failed"
        assert result["tool_results"][0]["code"] == "order_not_found"
        assert result["order_data"] == {}
        assert result["order_context"] is None


def test_order_tool_argument_validation_and_write_tool_rejection(service):
    for payload in (
        {"name": "get_order_details", "order_id": " o "},
        {"name": "get_order_details"},
        {"name": "get_customer_orders", "order_id": "o"},
        {"name": "confirm_and_execute", "order_id": "o"},
    ):
        with pytest.raises(ValidationError):
            OrderToolCall.model_validate(payload)
    sid = verified(service)
    with pytest.raises(BusinessError, match="order_not_found"):
        execute_order_tool(
            service, sid, OrderToolCall(name="get_order_details", order_id="missing")
        )


def test_real_model_status_alias_selects_minimum_read_tool(service):
    from app.multi_agent.order_agent import DeterministicOrderSelector

    triage = MockTriage().classify("查询订单o状态")
    triage = triage.model_copy(update={"requested_action": "check_status"})
    task = supervise(triage, new_agent_state("s", user_id="u"))["task_plan"][0]
    assert DeterministicOrderSelector().select(task, triage) == {
        "name": "get_order_status",
        "order_id": "o",
    }


def test_scripted_llm_status_alias_runs_status_tool_only(service):
    import json

    from app.llm import ModelReply
    from app.multi_agent.triage import LLMTriage

    class ScriptedProvider:
        def complete(self, messages, tools):
            assert tools == []
            return ModelReply(
                content=json.dumps(
                    {
                        "intent": "order_query",
                        "intents": ["order_query"],
                        "order_id": "o",
                        "requested_action": "check_status",
                        "confidence": 0.7,
                        "reasoning_summary": "Order status request.",
                    }
                )
            )

    sid = verified(service)
    result = run_turn(
        service, sid, "Check order o status", LLMTriage(ScriptedProvider()), SessionStateStore()
    )
    assert result["task_status"] == "queried"
    assert result["tool_results"][0]["tool"] == "get_order_status"
    assert result["order_data"]["order-lookup"]["kind"] == "status"


def test_agent_cannot_run_injected_write_tool(service):
    sid = verified(service)
    triage = MockTriage().classify("取消订单o")
    state = apply_agent_update(
        new_agent_state(sid, user_id="u"),
        {
            "triage_result": triage,
            "order_id": "o",
            "task_plan": supervise(triage, new_agent_state(sid, user_id="u"))["task_plan"],
        },
    )

    class BadSelector:
        def select(self, task, triage):
            return {"name": "confirm_and_execute", "order_id": "o"}

    outcome = run_order_agent(service, sid, state, selector=BadSelector())
    assert outcome["tool_results"][0]["code"] == "tool_not_allowed"
    assert service.order(sid, "o")["status"] == "pending"


def test_service_denies_wrong_id_even_if_selector_chose_it(service):
    sid = verified(service, "v@example.invalid")
    triage = MockTriage().classify("查询订单missing详情")
    state = apply_agent_update(
        new_agent_state(sid, user_id="v"),
        {
            "triage_result": triage,
            "order_id": "missing",
            "task_plan": supervise(triage, new_agent_state(sid, user_id="v"))["task_plan"],
        },
    )

    class WrongIdSelector:
        def select(self, task, triage):
            return {"name": "get_order_details", "order_id": "o"}

    outcome = run_order_agent(service, sid, state, selector=WrongIdSelector())
    assert outcome["tool_results"][0]["code"] == "tool_arguments_invalid"
    assert outcome["order_data"] == {}
    with pytest.raises(BusinessError) as error:
        execute_order_tool(service, sid, OrderToolCall(name="get_order_details", order_id="o"))
    assert error.value.code == "order_not_found"


def test_database_exception_is_sanitized(service):
    sid = verified(service)
    triage = MockTriage().classify("查询订单o详情")
    state = apply_agent_update(
        new_agent_state(sid, user_id="u"),
        {
            "triage_result": triage,
            "order_id": "o",
            "task_plan": supervise(triage, new_agent_state(sid, user_id="u"))["task_plan"],
        },
    )

    class BrokenService:
        def order(self, session_id, order_id):
            raise SQLAlchemyError("private database text")

    outcome = run_order_agent(BrokenService(), sid, state)
    assert outcome["tool_results"][0]["code"] == "database_unavailable"
    assert "private database text" not in str(outcome)


def test_multiturn_clarification_and_composite_request(service):
    sid = verified(service)
    store = SessionStateStore()
    first = run_turn(service, sid, "查询订单状态", MockTriage(), store)
    assert first["task_status"] == "clarification"
    second = run_turn(service, sid, "o", MockTriage(), store)
    assert second["task_status"] == "queried"
    assert second["order_data"]["order-lookup"]["kind"] == "status"
    combined = run_turn(service, sid, "查询订单o状态并咨询退货政策", MockTriage(), store)
    assert combined["task_status"] == "partial"
    assert combined["task_plan"][0]["status"] == "completed"
    assert all(
        task["status"] in {"pending", "blocked", "ready"}
        for task in combined["task_plan"]
        if task["target_agent"] != "order"
    )
    assert combined["next_agent"] == "policy"
    assert len(combined["tool_results"]) == 1


def test_tool_limit_stops_after_one_call_for_two_ready_order_tasks(service):
    sid = verified(service)
    triage = MockTriage().classify("查询订单o状态并查看product p details")
    planned = supervise(triage, new_agent_state(sid, user_id="u"))["task_plan"]
    state = apply_agent_update(
        new_agent_state(sid, user_id="u"),
        {"triage_result": triage, "order_id": "o", "task_plan": planned},
    )
    outcome = run_order_agent(service, sid, state, max_calls=1)
    assert len(outcome["tool_results"]) == 1
    assert sum(task.status == "completed" for task in outcome["task_plan"]) == 1
    assert sum(task.status == "ready" for task in outcome["task_plan"]) == 1


def test_two_ready_order_tasks_both_complete_with_bounded_calls(service):
    sid = verified(service)
    result = run_turn(
        service,
        sid,
        "查询订单o状态并查看product p details",
        MockTriage(),
        SessionStateStore(),
    )
    assert result["task_status"] == "queried"
    assert set(result["order_data"]) == {"order-lookup", "product-lookup"}
    assert [entry["status"] for entry in result["tool_results"]] == ["ok", "ok"]
    assert result["order_context"] == {"order_id": "o", "status": "pending"}


def test_readonly_queries_do_not_create_operation_or_audit_rows(service):
    from app.database import AuditRow, ProposalRow

    sid = verified(service)
    run_turn(service, sid, "查询订单o详情", MockTriage(), SessionStateStore())
    with Session(service.engine) as db:
        assert db.scalar(select(ProposalRow)) is None
        assert db.scalar(select(AuditRow)) is None
    assert MAX_ORDER_TOOL_CALLS == 2
