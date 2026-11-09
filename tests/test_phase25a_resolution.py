from copy import deepcopy

import pytest
from app.config import Settings
from app.database import AuditRow, OrderRow, ProposalRow, UserRow
from app.multi_agent.models import OrderQueryResult, ResolutionProposal
from app.multi_agent.order_tools import OrderToolCall, execute_order_tool
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.resolution_agent import run_resolution_agent
from app.multi_agent.state import apply_agent_update, new_agent_state
from app.multi_agent.supervisor import supervise
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_turn
from sqlalchemy import func, select
from sqlalchemy.orm import Session

POLICY_CONTEXT = [
    {
        "source": "data/raw/tau2/policy.md",
        "section": "Generic action rules",
        "version": "test-version",
        "excerpt": "Actions require evidence, rule validation, and confirmation.",
        "chunk_id": "policy-test",
        "score": 1.0,
        "retrieval_method": "keyword",
    }
]


def verified(service, email="test@example.invalid"):
    sid = service.start()
    user_id = service.verify(sid, email=email)
    return sid, user_id


def policy_agent(service):
    return build_policy_agent(
        service.engine,
        Settings(
            _env_file=None,
            agent_provider="mock",
            policy_retrieval_strategy="keyword",
            policy_top_k=3,
        ),
    )


def update_order(service, *, status, payment=True):
    with Session(service.engine) as db, db.begin():
        row = db.get(OrderRow, "o")
        order = deepcopy(row.order_json)
        order["status"] = status
        if payment:
            order["payment_history"] = [
                {
                    "transaction_type": "payment",
                    "amount": 10.0,
                    "payment_method_id": "card",
                }
            ]
        row.order_json = order
        row.status = status
        user = db.get(UserRow, "u")
        profile = deepcopy(user.profile_json)
        profile["payment_methods"] = {"card": {"source": "credit_card"}}
        user.profile_json = profile


def resolution_state(service, message, parameters=None, *, user=True, status=None):
    if status is not None:
        update_order(service, status=status)
    sid, user_id = verified(service) if user else (service.start(), None)
    triage = MockTriage().classify(message)
    if parameters is not None:
        triage = triage.model_copy(update={"extracted_parameters": parameters})
    base = new_agent_state(sid, user_id=user_id)
    tasks = supervise(triage, base)["task_plan"]
    for task in tasks:
        if task.task_id == "order-lookup" or task.target_agent == "policy":
            task.status = "completed"
        elif task.target_agent == "resolution":
            task.status = "ready"
    update = {
        "triage_result": triage,
        "intent": triage.intent,
        "order_id": triage.order_id,
        "task_plan": tasks,
        "policy_context": POLICY_CONTEXT,
        "current_task": next(task.task_id for task in tasks if task.target_agent == "resolution"),
    }
    if user:
        result = execute_order_tool(
            service, sid, OrderToolCall(name="get_order_details", order_id="o")
        )
        update.update(
            order_data={"order-lookup": result},
            order_context={"order_id": "o", "status": result.order.status},
        )
    return sid, apply_agent_update(base, update)


def persisted_counts(service):
    with Session(service.engine) as db:
        return (
            db.scalar(select(func.count()).select_from(ProposalRow)),
            db.scalar(select(func.count()).select_from(AuditRow)),
        )


def test_eligible_cancel_is_validated_but_not_executed(service):
    sid, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
    )
    before = service.order(sid, "o")
    result = run_resolution_agent(service, state)
    proposal = result["resolution_proposal"]
    assert isinstance(proposal, ResolutionProposal)
    assert proposal.status == "pending_confirmation"
    assert proposal.eligibility_status == "eligible" and proposal.validated is True
    assert result["eligibility_result"].validated is True
    assert result["pending_action"]["proposal_id"] == proposal.proposal_id
    assert service.order(sid, "o") == before
    assert persisted_counts(service) == (0, 0)


@pytest.mark.parametrize("status", ["processed", "delivered", "cancelled"])
def test_ineligible_cancel_is_rejected_by_existing_rule(service, status):
    _, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
        status=status,
    )
    result = run_resolution_agent(service, state)
    assert result["task_status"] == "ineligible"
    assert result["eligibility_result"].rule_code == "order_status_invalid"
    assert result["pending_action"] is None


def test_modify_missing_parameters_requests_clarification(service):
    _, state = resolution_state(service, "帮我修改订单o", {})
    result = run_resolution_agent(service, state)
    assert result["task_status"] == "needs_clarification"
    assert "modification_type" in result["missing_information"]
    assert result["eligibility_result"].validated is False


def test_return_uses_order_and_policy_evidence(service):
    _, state = resolution_state(
        service,
        "我要退货订单o",
        {"item_quantities": "i:1", "payment_method_id": "card"},
        status="delivered",
    )
    proposal = run_resolution_agent(service, state)["resolution_proposal"]
    assert proposal.action_type == "return"
    assert proposal.status == "pending_confirmation"
    assert {item.evidence_type for item in proposal.supporting_evidence} == {"order", "policy"}
    assert proposal.policy_references[0].reference == "policy-test"


def test_exchange_nonexistent_variant_is_rejected(service):
    _, state = resolution_state(
        service,
        "我要换货订单o",
        {"item_ids": "i", "new_item_ids": "missing", "payment_method_id": "card"},
        status="delivered",
    )
    result = run_resolution_agent(service, state)
    assert result["eligibility_result"].rule_code == "variant_invalid"
    assert result["resolution_proposal"].status == "ineligible"


def test_missing_identity_and_missing_policy_fail_closed(service):
    _, unverified = resolution_state(service, "帮我取消订单o", user=False)
    denied = run_resolution_agent(service, unverified)
    assert denied["task_status"] == "needs_clarification"
    assert "identity_verification" in denied["missing_information"]

    _, verified_state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
    )
    no_policy = apply_agent_update(verified_state, {"policy_context": []})
    denied_policy = run_resolution_agent(service, no_policy)
    assert denied_policy["task_status"] == "needs_clarification"
    assert denied_policy["missing_information"] == ["policy_evidence"]


def test_invalid_generator_output_and_parameters_are_rejected(service):
    _, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
    )

    class BadGenerator:
        def generate(self, task, triage, order_status, policy_sections):
            return {
                "action_type": "cancel",
                "proposed_parameters": {"reason": "ordered by mistake", "admin": True},
                "eligibility_suggestion": "eligible",
                "missing_information": [],
                "explanation": "bad",
            }

    result = run_resolution_agent(service, state, generator=BadGenerator())
    assert result["task_status"] == "resolution_failed"
    assert result["resolution_proposal"] is None
    assert persisted_counts(service) == (0, 0)


def test_model_rule_conflict_is_flagged_and_rule_wins(service):
    _, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
        status="delivered",
    )

    class WrongGenerator:
        def generate(self, task, triage, order_status, policy_sections):
            return {
                "action_type": "cancel",
                "proposed_parameters": {"reason": "ordered by mistake"},
                "eligibility_suggestion": "eligible",
                "missing_information": [],
                "explanation": "model says yes",
            }

    result = run_resolution_agent(service, state, generator=WrongGenerator())
    assert result["eligibility_result"].status == "ineligible"
    assert result["resolution_proposal"].requires_human_review is True
    assert result["risk_flags"] == ["model_rule_conflict"]


def test_multiturn_reuses_order_and_keyword_policy_then_completes(service, monkeypatch):
    sid, _ = verified(service)
    store = SessionStateStore()
    calls = 0
    original = service.order

    def counted_order(session_id, order_id):
        nonlocal calls
        calls += 1
        return original(session_id, order_id)

    monkeypatch.setattr(service, "order", counted_order)
    first = run_turn(
        service,
        sid,
        "帮我取消订单o",
        MockTriage(),
        store,
        policy_agent=policy_agent(service),
    )
    assert first["task_status"] == "needs_clarification"
    assert first["policy_retrieval"]["method"] == "keyword"
    assert calls == 1
    second = run_turn(
        service,
        sid,
        "ordered by mistake",
        MockTriage(),
        store,
        policy_agent=policy_agent(service),
    )
    assert second["task_status"] == "proposal_ready"
    assert second["resolution_proposal"]["status"] == "pending_confirmation"
    assert calls == 1
    assert service.order(sid, "o")["status"] == "pending"
    assert persisted_counts(service) == (0, 0)


def test_order_failure_prevents_resolution(service):
    sid, _ = verified(service, "v@example.invalid")
    result = run_turn(
        service,
        sid,
        "帮我取消订单o because ordered by mistake",
        MockTriage(),
        SessionStateStore(),
        policy_agent=policy_agent(service),
    )
    assert result["task_status"] == "query_failed"
    assert result["resolution_proposal"] is None


def test_composite_plan_respects_dependencies(service):
    triage = MockTriage().classify(
        "查询订单o状态并帮我取消订单o because ordered by mistake"
    )
    plan = supervise(triage, new_agent_state("s", user_id="u"))["task_plan"]
    tasks = {task.task_id: task for task in plan}
    assert tasks["cancel_order-proposal"].dependencies == [
        "order-lookup",
        "cancel_order-policy",
    ]
    assert tasks["cancel_order-guard"].dependencies == ["cancel_order-proposal"]
    assert tasks["cancel_order-proposal"].status == "pending"


def test_sessions_and_duplicate_proposal_ids_are_isolated(service):
    sid, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
    )
    first = run_resolution_agent(service, state)["resolution_proposal"]
    repeated = run_resolution_agent(service, state)["resolution_proposal"]
    assert first.proposal_id == repeated.proposal_id

    other = service.start()
    service.verify(other, email="test@example.invalid")
    other_state = apply_agent_update(
        new_agent_state(other, user_id="u"),
        {
            "triage_result": state["triage_result"],
            "intent": state["intent"],
            "order_id": "o",
            "order_context": state["order_context"],
            "order_data": state["order_data"],
            "policy_context": POLICY_CONTEXT,
            "task_plan": state["task_plan"],
            "current_task": state["current_task"],
        },
    )
    isolated = run_resolution_agent(service, other_state)["resolution_proposal"]
    assert isolated.proposal_id != first.proposal_id
    assert sid != other


def test_readonly_validator_and_agent_have_no_business_write_effect(service):
    sid, state = resolution_state(
        service,
        "帮我取消订单o because ordered by mistake",
        {"reason": "ordered by mistake"},
    )
    original = service.order(sid, "o")
    delta = run_resolution_agent(service, state)
    assert [entry["tool"] for entry in delta["tool_results"]] == [
        "validate_action_readonly"
    ]
    assert service.order(sid, "o") == original
    assert persisted_counts(service) == (0, 0)


def test_existing_interfaces_remain_available():
    from app.agent import chat_once
    from app.live_agent import live_chat
    from app.main import app

    paths = {route.path for route in app.routes}
    assert callable(chat_once) and callable(live_chat)
    assert "/api/v1/chat" in paths
    assert "/api/v1/operations" in paths
    assert "/api/v1/debug/plan" in paths
    assert OrderQueryResult.model_fields["source"].default == "business_database"
