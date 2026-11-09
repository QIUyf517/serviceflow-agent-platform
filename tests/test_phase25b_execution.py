from copy import deepcopy

import pytest
from app.database import (
    ConfirmationRecordRow,
    ExecutionAuditRow,
    ExecutionRequestRow,
    OrderRow,
    SessionRow,
)
from app.multi_agent.execution import ExecutionService
from app.multi_agent.order_tools import OrderToolCall, execute_order_tool
from app.multi_agent.resolution_agent import run_resolution_agent
from app.multi_agent.state import apply_agent_update, new_agent_state
from app.multi_agent.supervisor import supervise
from app.multi_agent.triage import MockTriage
from app.service import BusinessError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

POLICY_CONTEXT = [
    {
        "source": "data/raw/tau2/policy.md",
        "section": "Cancel pending order",
        "version": "test-version",
        "excerpt": "Pending orders may be cancelled for an allowed reason after confirmation.",
        "chunk_id": "policy-cancel-test",
        "score": 1.0,
        "retrieval_method": "keyword",
    }
]


def verified(service, email="test@example.invalid"):
    sid = service.start()
    user_id = service.verify(sid, email=email)
    return sid, user_id


def cancel_proposal(service, *, sid=None, reason="ordered by mistake", order_id="o"):
    if sid is None:
        sid, user_id = verified(service)
    else:
        with Session(service.engine) as db:
            user_id = db.get(SessionRow, sid).user_id
    triage = MockTriage().classify(f"帮我取消订单{order_id} because {reason}")
    triage = triage.model_copy(update={"extracted_parameters": {"reason": reason}})
    base = new_agent_state(sid, user_id=user_id)
    tasks = supervise(triage, base)["task_plan"]
    for task in tasks:
        if task.task_id == "order-lookup" or task.target_agent == "policy":
            task.status = "completed"
        elif task.target_agent == "resolution":
            task.status = "ready"
    order_result = execute_order_tool(
        service,
        sid,
        OrderToolCall(name="get_order_details", order_id=order_id),
    )
    state = apply_agent_update(
        base,
        {
            "triage_result": triage,
            "intent": triage.intent,
            "order_id": order_id,
            "order_context": {"order_id": order_id, "status": order_result.order.status},
            "order_data": {"order-lookup": order_result},
            "policy_context": POLICY_CONTEXT,
            "task_plan": tasks,
            "current_task": "cancel_order-proposal",
        },
    )
    delta = run_resolution_agent(service, state)
    return sid, delta["resolution_proposal"], delta["eligibility_result"]


def prepare(service, *, key="idem-cancel-00000001", reason="ordered by mistake"):
    sid, proposal, eligibility = cancel_proposal(service, reason=reason)
    execution = ExecutionService(service.engine)
    request = execution.prepare_cancel(sid, proposal, eligibility, key)
    return execution, sid, request


def confirm(execution, sid, request, *, decision="confirm"):
    return execution.record_decision(
        sid,
        request.request_id,
        decision=decision,
        confirmation_text=request.confirmation_text,
    )


def test_normal_cancel_requires_bound_confirmation_and_writes_once(service):
    execution, sid, request = prepare(service)
    assert service.order(sid, "o")["status"] == "pending"
    confirmation = confirm(execution, sid, request)
    result = execution.execute_cancel(
        sid, request.request_id, idempotency_key=request.idempotency_key
    )
    assert result.confirmation_id == confirmation.confirmation_id
    assert result.before_status == "pending" and result.after_status == "cancelled"
    assert service.order(sid, "o")["status"] == "cancelled"
    with Session(service.engine) as db:
        assert db.get(OrderRow, "o").row_version == 2
        assert db.scalar(select(func.count()).select_from(ExecutionRequestRow)) == 1
        assert db.scalar(select(func.count()).select_from(ConfirmationRecordRow)) == 1


@pytest.mark.parametrize("status", ["processed", "cancelled"])
def test_non_pending_or_already_cancelled_order_is_rejected(service, status):
    with Session(service.engine) as db, db.begin():
        row = db.get(OrderRow, "o")
        payload = deepcopy(row.order_json)
        payload["status"] = status
        row.order_json = payload
        row.status = status
    sid, proposal, eligibility = cancel_proposal(service)
    assert proposal.status == "ineligible"
    with pytest.raises(BusinessError, match="proposal_not_executable"):
        ExecutionService(service.engine).prepare_cancel(
            sid, proposal, eligibility, "idem-ineligible-0001"
        )


def test_unverified_and_foreign_sessions_cannot_prepare(service):
    owner_sid, proposal, eligibility = cancel_proposal(service)
    unverified = service.start()
    with pytest.raises(BusinessError, match="identity_required"):
        ExecutionService(service.engine).prepare_cancel(
            unverified, proposal, eligibility, "idem-unverified-0001"
        )
    other, _ = verified(service, "v@example.invalid")
    with pytest.raises(BusinessError, match="order_not_found"):
        ExecutionService(service.engine).prepare_cancel(
            other, proposal, eligibility, "idem-foreign-user-01"
        )
    assert service.order(owner_sid, "o")["status"] == "pending"


def test_execute_without_confirmation_does_not_change_or_consume_request(service):
    execution, sid, request = prepare(service)
    with pytest.raises(BusinessError, match="confirmation_required"):
        execution.execute_cancel(
            sid, request.request_id, idempotency_key=request.idempotency_key
        )
    assert service.order(sid, "o")["status"] == "pending"
    assert execution.get_request(sid, request.request_id).status == "pending_confirmation"


def test_explicit_rejection_blocks_execution(service):
    execution, sid, request = prepare(service)
    rejected = confirm(execution, sid, request, decision="reject")
    assert rejected.status == "rejected"
    with pytest.raises(BusinessError, match="confirmation_rejected"):
        execution.execute_cancel(
            sid, request.request_id, idempotency_key=request.idempotency_key
        )
    assert service.order(sid, "o")["status"] == "pending"


def test_expired_confirmation_is_persistently_rejected(service):
    now = [1000.0]
    sid, proposal, eligibility = cancel_proposal(service)
    execution = ExecutionService(service.engine, confirmation_ttl_seconds=10, clock=lambda: now[0])
    request = execution.prepare_cancel(
        sid, proposal, eligibility, "idem-expired-confirm-1"
    )
    now[0] = 1011.0
    with pytest.raises(BusinessError, match="confirmation_expired"):
        confirm(execution, sid, request)
    assert execution.get_request(sid, request.request_id).status == "expired"
    assert service.order(sid, "o")["status"] == "pending"


def test_confirmation_text_is_bound_to_exact_operation(service):
    execution, sid, request = prepare(service)
    wrong = request.confirmation_text.replace("order=o", "order=other")
    with pytest.raises(BusinessError, match="confirmation_text_mismatch"):
        execution.record_decision(
            sid,
            request.request_id,
            decision="confirm",
            confirmation_text=wrong,
        )
    assert execution.get_request(sid, request.request_id).status == "pending_confirmation"


def test_confirmation_record_for_wrong_order_cannot_execute(service):
    execution, sid, request = prepare(service)
    confirmation = confirm(execution, sid, request)
    with Session(service.engine) as db, db.begin():
        original = db.get(OrderRow, "o")
        payload = deepcopy(original.order_json)
        payload["order_id"] = "o2"
        db.add(
            OrderRow(
                source_order_id="o2",
                source_user_id="u",
                status="pending",
                order_json=payload,
                row_version=1,
            )
        )
        record = db.get(ConfirmationRecordRow, confirmation.confirmation_id)
        record.order_id = "o2"
    with pytest.raises(BusinessError, match="confirmation_binding_invalid"):
        execution.execute_cancel(
            sid, request.request_id, idempotency_key=request.idempotency_key
        )
    assert service.order(sid, "o")["status"] == "pending"


def test_parameter_change_after_confirmation_invalidates_execution(service):
    execution, sid, request = prepare(service)
    confirm(execution, sid, request)
    with Session(service.engine) as db, db.begin():
        row = db.get(ExecutionRequestRow, request.request_id)
        arguments = deepcopy(row.arguments)
        arguments["reason"] = "no longer needed"
        row.arguments = arguments
    with pytest.raises(BusinessError, match="proposal_binding_invalid"):
        execution.execute_cancel(
            sid, request.request_id, idempotency_key=request.idempotency_key
        )
    assert service.order(sid, "o")["status"] == "pending"
    assert execution.get_confirmation(sid, request.request_id).status == "invalidated"


def test_idempotent_prepare_and_execute_return_one_effect(service):
    sid, proposal, eligibility = cancel_proposal(service)
    execution = ExecutionService(service.engine)
    first = execution.prepare_cancel(sid, proposal, eligibility, "idem-replay-cancel-01")
    repeated = execution.prepare_cancel(sid, proposal, eligibility, "idem-replay-cancel-01")
    assert repeated.request_id == first.request_id
    confirm(execution, sid, first)
    result = execution.execute_cancel(
        sid, first.request_id, idempotency_key=first.idempotency_key
    )
    replay = execution.execute_cancel(
        sid, first.request_id, idempotency_key=first.idempotency_key
    )
    assert replay.request_id == result.request_id and replay.idempotent_replay is True
    with Session(service.engine) as db:
        assert db.get(OrderRow, "o").row_version == 2
        success = db.scalars(
            select(ExecutionAuditRow).where(
                ExecutionAuditRow.event_type == "execution_succeeded"
            )
        ).all()
        assert len(success) == 1


def test_idempotency_key_cannot_be_rebound_to_other_parameters(service):
    sid, first_proposal, first_eligibility = cancel_proposal(service)
    _, second_proposal, second_eligibility = cancel_proposal(
        service, sid=sid, reason="no longer needed"
    )
    execution = ExecutionService(service.engine)
    execution.prepare_cancel(
        sid, first_proposal, first_eligibility, "idem-conflict-cancel1"
    )
    with pytest.raises(BusinessError, match="idempotency_key_conflict"):
        execution.prepare_cancel(
            sid, second_proposal, second_eligibility, "idem-conflict-cancel1"
        )


def test_transaction_exception_rolls_back_order_and_records_failure(service):
    execution, sid, request = prepare(service)
    confirm(execution, sid, request)

    def fail(stage):
        assert stage == "before_commit"
        raise SQLAlchemyError("injected")

    broken = ExecutionService(service.engine, fault_injector=fail)
    with pytest.raises(BusinessError, match="database_transaction_failed"):
        broken.execute_cancel(
            sid, request.request_id, idempotency_key=request.idempotency_key
        )
    assert service.order(sid, "o")["status"] == "pending"
    with Session(service.engine) as db:
        assert db.get(OrderRow, "o").row_version == 1
        request_row = db.get(ExecutionRequestRow, request.request_id)
        assert request_row.status == "failed"
        assert db.scalar(
            select(func.count())
            .select_from(ExecutionAuditRow)
            .where(ExecutionAuditRow.event_type == "execution_failed")
        ) == 1


def test_audit_contains_distinct_lifecycle_events_and_no_profile(service):
    execution, sid, request = prepare(service)
    confirm(execution, sid, request)
    execution.execute_cancel(
        sid, request.request_id, idempotency_key=request.idempotency_key
    )
    events = execution.audit_events(sid, request.request_id)
    assert {event["event_type"] for event in events} == {
        "proposal_generated",
        "eligibility_validated",
        "user_confirmed",
        "execution_succeeded",
    }
    success = next(event for event in events if event["event_type"] == "execution_succeeded")
    assert success["task_id"] == "cancel_order-proposal"
    assert success["before_status"] == "pending"
    assert success["after_status"] == "cancelled"
    assert success["confirmation_id"]
    assert "email" not in str(events).lower() and "api_key" not in str(events).lower()


def test_agent_state_cannot_self_authorize_confirmation(service):
    from app.multi_agent.state import apply_agent_update

    with pytest.raises(ValueError, match="protected_state_field"):
        apply_agent_update(new_agent_state("s"), {"user_confirmed": True})
