"""Coherent multi-turn cancel/return conversation over specialized agents."""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.database import SessionRow
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import ConfirmationRecord, ExecutionRequestSummary
from app.multi_agent.policy_agent import PolicyAgent
from app.multi_agent.state import AgentState, apply_agent_update
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_execution_turn, run_turn
from app.service import BusinessError, RetailService

CONFIRM_WORDS = {"确认", "确认取消", "同意", "是", "yes", "confirm", "i confirm"}
REJECT_WORDS = {"拒绝", "拒绝取消", "不取消了", "不同意", "否", "no", "reject"}
CONFIRM_WORDS.update({"确认退货", "确认提交退货申请"})
REJECT_WORDS.update({"拒绝退货", "不退了"})


def _metrics(began: float, trace: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict:
    return {
        "elapsed_ms": max(0, int((perf_counter() - began) * 1000)),
        "node_count": len(trace),
        "tool_calls": len(tools),
        "nodes": [event.get("node") for event in trace],
        "node_timings_ms": [
            {
                "node": event.get("node"),
                "elapsed_ms": event.get("elapsed_ms"),
                "result": event.get("status"),
                "error_code": event.get("code"),
            }
            for event in trace
        ],
        "provider": "mock_local",
        "model": "deterministic-v1",
        "run_config": {"temperature": None, "seed": None},
        "token_usage": None,
    }


def _response(
    began: float,
    *,
    task_status: str,
    final_response: str,
    trace: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    request: ExecutionRequestSummary | None = None,
    proposal: dict[str, Any] | None = None,
    eligibility: dict[str, Any] | None = None,
    execution_result: dict[str, Any] | None = None,
    failure_reason: str | None = None,
    task_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": next(
            (event.get("trace_id") for event in trace if event.get("trace_id")), None
        ),
        "task_status": task_status,
        "request_id": request.request_id if request else None,
        "pending_confirmation": request.model_dump() if request else None,
        "resolution_proposal": proposal,
        "eligibility_result": eligibility,
        "execution_result": execution_result,
        "failure_reason": failure_reason,
        "task_plan": task_plan or [],
        "trace": trace,
        "tool_results": tool_results,
        "final_response": final_response,
        "metrics": _metrics(began, trace, tool_results),
    }


def _current_request(store: SessionStateStore, sid: str) -> str | None:
    with store.lock:
        state = store.states.get(sid)
        request = state["execution_request"] if state else None
        return request.request_id if request else None


def _same_action(message: str, request: ExecutionRequestSummary) -> bool:
    try:
        triage = MockTriage().classify(message)
    except ValueError:
        return False
    if triage.order_id != request.order_id:
        return False
    if request.action_type == "cancel":
        return (
            "cancel_order" in triage.intents
            and triage.extracted_parameters.get("reason")
            == request.proposed_parameters.get("reason")
        )
    return (
        "return_order" in triage.intents
        and triage.extracted_parameters.get("item_quantities")
        == ",".join(
            f"{key}:{value}"
            for key, value in request.proposed_parameters.get("item_quantities", {}).items()
        )
        and triage.extracted_parameters.get("payment_method_id")
        == request.proposed_parameters.get("payment_method_id")
    )


def _store_pending(
    store: SessionStateStore,
    sid: str,
    request: ExecutionRequestSummary,
) -> AgentState:
    with store.lock:
        state = store.states[sid]
        tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
        for task in tasks:
            if task.target_agent == "confirmation":
                task.status = "blocked"
                task.required_inputs = ["user_confirmation"]
        response = (
            f"待确认：{request.summary}。如确认，请回复“确认”或回显："
            f"{request.confirmation_text}；如拒绝，请回复“拒绝”。"
        )
        updated = apply_agent_update(
            state,
            {
                "task_plan": tasks,
                "execution_request": request,
                "task_status": "pending_confirmation",
                "current_task": f"{request.action_type}_order-confirmation",
                "next_agent": "end",
                "final_response": response,
                "messages": [AIMessage(content=response)],
                "trace": [{"node": "confirmation", "status": "waiting"}],
            },
        )
        store.states[sid] = deepcopy(updated)
        return updated


def _store_rejection(
    store: SessionStateStore,
    sid: str,
    request: ExecutionRequestSummary,
    confirmation: ConfirmationRecord,
) -> AgentState:
    with store.lock:
        state = store.states.get(sid)
        if state is None:
            raise BusinessError("task_state_not_found", 404)
        tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
        for task in tasks:
            if task.target_agent == "confirmation":
                task.status = "completed"
                task.required_inputs = []
            elif task.target_agent == "executor":
                task.status = "blocked"
                task.required_inputs = ["confirmation_rejected"]
        operation = "取消订单" if request.action_type == "cancel" else "退货申请"
        response = f"已拒绝{operation} {request.order_id}；订单未被修改。"
        updated = apply_agent_update(
            state,
            {
                "task_plan": tasks,
                "execution_request": request,
                "confirmation_record": confirmation,
                "pending_action": None,
                "task_status": "confirmation_rejected",
                "current_task": None,
                "next_agent": "end",
                "final_response": response,
                "messages": [AIMessage(content=response)],
                "trace": [{"node": "confirmation", "status": "rejected"}],
                "tool_results": [
                    {"tool": "confirmation_gate", "status": "error", "code": "rejected"}
                ],
            },
        )
        store.states[sid] = deepcopy(updated)
        return updated


def _failure(
    began: float,
    store: SessionStateStore,
    sid: str,
    request: ExecutionRequestSummary | None,
    error: BusinessError,
) -> dict[str, Any]:
    response = f"操作未执行：{error.code}。数据库订单状态未被宣称为已修改。"
    trace = [{"node": "supervisor_result", "status": "execution_failed", "code": error.code}]
    action = request.action_type if request else "unknown"
    tools = [{"tool": f"execute_{action}_controlled", "status": "error", "code": error.code}]
    with store.lock:
        state = store.states.get(sid)
        if state is not None:
            try:
                updated = apply_agent_update(
                    state,
                    {
                        "task_status": "execution_failed",
                        "next_agent": "end",
                        "final_response": response,
                        "messages": [AIMessage(content=response)],
                        "errors": [error.code],
                        "trace": trace,
                        "tool_results": tools,
                    },
                )
                store.states[sid] = deepcopy(updated)
            except ValueError:
                pass
    return _response(
        began,
        task_status="execution_failed",
        final_response=response,
        trace=trace,
        tool_results=tools,
        request=request,
        failure_reason=error.code,
    )


def run_after_sales_conversation(
    service: RetailService,
    execution: ExecutionService,
    sid: str,
    message: str,
    store: SessionStateStore,
    policy_agent: PolicyAgent,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run one natural-language turn; confirmation decisions are deterministic."""
    began = perf_counter()
    phrase = message.strip()
    if not phrase:
        raise BusinessError("message_required")
    active_id = request_id or _current_request(store, sid)
    if active_id is not None:
        request = execution.get_request(sid, active_id)
        confirm_text, reject_text = execution.confirmation_phrases(sid, active_id)
        normalized = phrase.casefold()
        is_confirm = phrase == confirm_text or normalized in CONFIRM_WORDS
        is_reject = phrase == reject_text or normalized in REJECT_WORDS
        if is_confirm:
            try:
                execution.record_decision(
                    sid,
                    active_id,
                    decision="confirm",
                    confirmation_text=confirm_text,
                )
                result = run_execution_turn(
                    execution, sid, active_id, request.idempotency_key, store
                )
            except BusinessError as exc:
                return _failure(began, store, sid, request, exc)
            return _response(
                began,
                task_status=result["task_status"],
                final_response=result["final_response"],
                trace=result["trace"],
                tool_results=result["tool_results"],
                request=execution.get_request(sid, active_id),
                execution_result=result["execution_result"],
                task_plan=result["task_plan"],
            )
        if is_reject:
            try:
                confirmation = execution.record_decision(
                    sid,
                    active_id,
                    decision="reject",
                    confirmation_text=confirm_text,
                )
                request = execution.get_request(sid, active_id)
                state = _store_rejection(store, sid, request, confirmation)
            except BusinessError as exc:
                return _failure(began, store, sid, request, exc)
            trace = [{"node": "confirmation", "status": "rejected"}]
            tools = [{"tool": "confirmation_gate", "status": "error", "code": "rejected"}]
            return _response(
                began,
                task_status="confirmation_rejected",
                final_response=state["final_response"] or "Cancellation rejected.",
                trace=trace,
                tool_results=tools,
                request=request,
                task_plan=[task.model_dump() for task in state["task_plan"]],
            )
        if request.status == "pending_confirmation" and _same_action(phrase, request):
            return _response(
                began,
                task_status="pending_confirmation",
                final_response=(
                    f"该方案仍待确认：{request.summary}。请回复“确认”或“拒绝”。"
                ),
                trace=[{"node": "confirmation", "status": "waiting"}],
                tool_results=[],
                request=request,
            )
        execution.supersede_request(sid, active_id)

    outcome = run_turn(service, sid, phrase, MockTriage(), store, policy_agent=policy_agent)
    proposal = outcome["resolution_proposal"]
    eligibility = outcome["eligibility_result"]
    if (
        outcome["task_status"] == "proposal_ready"
        and proposal is not None
        and proposal["action_type"] in {"cancel", "return"}
        and eligibility is not None
    ):
        with store.lock:
            state = store.states[sid]
            proposal_model = state["resolution_proposal"]
            eligibility_model = state["eligibility_result"]
            if proposal_model is None or eligibility_model is None:
                raise BusinessError("resolution_state_missing", 409)
            proposal_model = proposal_model.model_copy(deep=True)
            eligibility_model = eligibility_model.model_copy(deep=True)
        request = execution.prepare_action(
            sid,
            proposal_model,
            eligibility_model,
            "chat-" + uuid4().hex,
        )
        waiting_began = perf_counter()
        state = _store_pending(store, sid, request)
        trace = outcome["trace"] + [
            {
                "node": "confirmation",
                "status": "waiting",
                "trace_id": outcome["trace_id"],
                "task_id": f"{request.action_type}_order-confirmation",
                "request_id": request.request_id,
                "elapsed_ms": max(0.0, (perf_counter() - waiting_began) * 1000),
            }
        ]
        return _response(
            began,
            task_status="pending_confirmation",
            final_response=state["final_response"] or "Action is pending confirmation.",
            trace=trace,
            tool_results=outcome["tool_results"],
            request=request,
            proposal=proposal,
            eligibility=eligibility,
            task_plan=[task.model_dump() for task in state["task_plan"]],
        )
    return _response(
        began,
        task_status=outcome["task_status"],
        final_response=outcome["final_response"],
        trace=outcome["trace"],
        tool_results=outcome["tool_results"],
        proposal=proposal,
        eligibility=eligibility,
        failure_reason=(outcome["errors"][-1] if outcome.get("errors") else None),
        task_plan=outcome["task_plan"],
    )


# Backward-compatible import name retained for existing 2.5C callers.
run_cancel_conversation = run_after_sales_conversation


def current_task_progress(
    service: RetailService,
    execution: ExecutionService,
    sid: str,
    store: SessionStateStore,
) -> dict[str, Any]:
    with Session(service.engine) as db:
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        if session.user_id is None:
            raise BusinessError("identity_required", 403)
    with store.lock:
        state = store.states.get(sid)
        if state is None:
            raise BusinessError("task_state_not_found", 404)
        snapshot = deepcopy(state)
    request = snapshot["execution_request"]
    persisted = execution.get_request(sid, request.request_id) if request else None
    return {
        "thread_id": snapshot["thread_id"],
        "task_status": snapshot["task_status"],
        "current_task": snapshot["current_task"],
        "task_plan": [task.model_dump() for task in snapshot["task_plan"]],
        "order_context": snapshot["order_context"],
        "policy_context": snapshot["policy_context"],
        "resolution_proposal": (
            snapshot["resolution_proposal"].model_dump()
            if snapshot["resolution_proposal"]
            else None
        ),
        "eligibility_result": (
            snapshot["eligibility_result"].model_dump()
            if snapshot["eligibility_result"]
            else None
        ),
        "pending_confirmation": persisted.model_dump() if persisted else None,
        "execution_result": (
            snapshot["execution_result"].model_dump() if snapshot["execution_result"] else None
        ),
        "trace": snapshot["trace"],
        "final_response": snapshot["final_response"],
    }
