import pytest
from app.multi_agent.state import new_agent_state
from app.multi_agent.supervisor import MAX_ROUTES, safe_target, supervise
from app.multi_agent.triage import MockTriage, TriageError
from app.multi_agent.workflow import SessionStateStore, run_turn
from app.service import BusinessError


def test_supervisor_order_query_requires_identity_and_order():
    triage = MockTriage().classify("查询订单状态")
    plan = supervise(triage, new_agent_state("s"))
    assert plan["task_status"] == "clarification"
    assert plan["next_agent"] == "end"
    assert set(plan["missing_information"]) == {"order_id", "identity_verification"}
    assert plan["task_plan"][0].status == "blocked"


def test_supervisor_return_plan_has_dependencies_and_no_execution():
    triage = MockTriage().classify("帮我看看订单123能不能退货，如果可以就申请退货")
    plan = supervise(triage, new_agent_state("s", user_id="u"))
    tasks = {task.task_id: task for task in plan["task_plan"]}
    assert plan["next_agent"] == "order"
    assert tasks["order-lookup"].status == "ready"
    assert tasks["return_order-proposal"].dependencies == [
        "order-lookup",
        "return_order-policy",
    ]
    assert tasks["return_order-guard"].dependencies == ["return_order-proposal"]
    assert tasks["return_order-confirmation"].dependencies == ["return_order-guard"]
    assert tasks["return_order-execute"].status == "pending"
    assert all(task.status != "completed" for task in tasks.values())


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("取消订单123", "cancel_order"),
        ("修改订单123", "modify_order"),
        ("退货订单123", "return_order"),
        ("换货订单123", "exchange_order"),
    ],
)
def test_write_requests_only_plan_guard_confirmation_and_execution(message, intent):
    plan = supervise(MockTriage().classify(message), new_agent_state("s", user_id="u"))
    tasks = {task.task_id: task for task in plan["task_plan"]}
    assert plan["next_agent"] == "order"
    assert tasks[f"{intent}-proposal"].dependencies == [
        "order-lookup",
        f"{intent}-policy",
    ]
    assert tasks[f"{intent}-guard"].dependencies == [f"{intent}-proposal"]
    assert tasks[f"{intent}-confirmation"].dependencies == [f"{intent}-guard"]
    assert tasks[f"{intent}-execute"].status == "pending"


def test_repeated_planning_replaces_plan_instead_of_duplicating_steps():
    state = new_agent_state("s", user_id="u")
    triage = MockTriage().classify("取消订单123")
    first = supervise(triage, state)
    state["routing_count"] = first["routing_count"]
    second = supervise(triage, state)
    assert [step.task_id for step in first["task_plan"]] == [
        step.task_id for step in second["task_plan"]
    ]
    assert len({step.task_id for step in second["task_plan"]}) == len(second["task_plan"])


def test_supervisor_policy_only_is_ready_without_identity():
    plan = supervise(MockTriage().classify("售后政策是什么"), new_agent_state("s"))
    assert plan["next_agent"] == "policy"
    assert plan["task_status"] == "planned"


def test_invalid_route_and_route_limit_fail_closed():
    assert safe_target("invented_agent") == "end"
    assert safe_target("executor") == "end"
    state = new_agent_state("s", user_id="u")
    state["routing_count"] = MAX_ROUTES
    plan = supervise(MockTriage().classify("查询订单123"), state)
    assert plan["next_agent"] == "end"
    assert plan["task_status"] == "route_limit"


def test_workflow_multiturn_updates_same_task_and_keeps_session_isolation(service):
    store = SessionStateStore()
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    first = run_turn(service, sid, "查询订单状态", MockTriage(), store)
    assert first["task_status"] == "clarification"
    assert first["triage"]["order_id"] is None
    assert first["task_plan"][0]["task_id"] == "order-lookup"
    second = run_turn(service, sid, "o", MockTriage(), store)
    assert second["triage"]["order_id"] == "o"
    assert second["task_plan"][0]["task_id"] == "order-lookup"
    assert second["next_agent"] == "end"
    assert second["task_status"] == "queried"
    assert second["order_data"]["order-lookup"]["status"] == "pending"
    assert [event["node"] for event in second["trace"]] == [
        "triage",
        "supervisor",
        "order",
        "supervisor_result",
        "terminal",
    ]
    assert len(store.states[sid]["messages"]) == 4
    other = service.start()
    service.verify(other, email="v@example.invalid")
    separate = run_turn(service, other, "查询订单状态", MockTriage(), store)
    assert separate["triage"]["order_id"] is None
    assert store.states[other]["user_id"] == "v"
    assert store.states[sid]["user_id"] == "u"
    assert store.states[other]["thread_id"] != store.states[sid]["thread_id"]


def test_workflow_unknown_and_provider_failure_stop_safely(service):
    sid = service.start()
    unknown = run_turn(service, sid, "你好", MockTriage(), SessionStateStore())
    assert unknown["task_status"] == "unsupported"
    assert unknown["task_plan"] == []
    assert unknown["next_agent"] == "end"

    class BrokenTriage:
        def classify(self, message, previous=None):
            raise TriageError("provider_unavailable")

    failure = run_turn(service, sid, "查询订单123", BrokenTriage(), SessionStateStore())
    assert failure["task_status"] == "triage_error"
    assert failure["next_agent"] == "end"


def test_workflow_rejects_nonexistent_session(service):
    with pytest.raises(BusinessError, match="session_not_found"):
        run_turn(service, "missing", "查询订单123", MockTriage(), SessionStateStore())


def test_existing_single_agent_interfaces_still_callable():
    from app.agent import chat_once
    from app.live_agent import live_chat
    from app.main import app

    assert callable(chat_once) and callable(live_chat)
    assert any(route.path == "/api/v1/chat" for route in app.routes)
