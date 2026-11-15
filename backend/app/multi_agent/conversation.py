"""Coherent multi-turn cancel/return conversation over specialized agents."""

from __future__ import annotations

import re
from copy import deepcopy
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import PolicyChunkRow, PolicyDocumentRow, SessionRow
from app.multi_agent.content_safety import ContentSafetyChecker, blocked_message
from app.multi_agent.customer_presenter import (
    clarification,
    policy_answer,
    query_answer,
    status_label,
)
from app.multi_agent.execution import ExecutionService
from app.multi_agent.message_store import MessageStore
from app.multi_agent.models import ConfirmationRecord, ExecutionRequestSummary
from app.multi_agent.policy_agent import PolicyAgent
from app.multi_agent.state import AgentState, apply_agent_update
from app.multi_agent.triage import (
    ORDER_ID,
    MockTriage,
    ThreadScopedTriage,
    mentioned_order_ids,
)
from app.multi_agent.workflow import SessionStateStore, run_execution_turn, run_turn
from app.service import BusinessError, RetailService
from app.ticketing import TicketService, ticket_idempotency_key

CONFIRM_WORDS = {"确认", "确认取消", "同意", "是", "yes", "confirm", "i confirm"}
REJECT_WORDS = {
    "拒绝",
    "拒绝取消",
    "不取消了",
    "不想取消",
    "不想取消了",
    "不同意",
    "否",
    "no",
    "reject",
}
CONFIRM_WORDS.update({"确认退货", "确认提交退货申请"})
REJECT_WORDS.update({"拒绝退货", "不退了"})
HUMAN_REQUEST = re.compile(
    r"^(?:人工客服|转人工|找客服)$"
    r"|(?:请|帮我|我要|我想|我需要|能否|麻烦)?"
    r"(?:转|找|联系|接入|换)(?:一下|到|个)?(?:人工|人工客服|真人客服)"
    r"|\b(?:talk|speak|connect|transfer).{0,12}(?:human|operator|live agent)\b",
    re.I,
)
OUT_OF_SCOPE = re.compile(
    r"(?:唱歌|唱首歌|讲笑话|写代码|编程作业|股票推荐|医疗诊断|游戏攻略|天气预报)"
    r"|\b(?:sing (?:me )?a song|tell (?:me )?a joke|write code|weather forecast|stock tip)\b",
    re.I,
)
HUMAN_SUGGESTION = "如需人工客服，请回复“转人工”。"
UNRESOLVED_NOTICE = "智能客服当前无法解决这个问题。"


def _rehydrate_policy_context(service: RetailService, state: AgentState) -> list[dict[str, Any]]:
    """Resolve safe checkpoint references back to source-backed policy excerpts."""
    proposal = state["resolution_proposal"]
    if proposal is None or not proposal.policy_references:
        return []
    references = {reference.reference for reference in proposal.policy_references}
    with Session(service.engine) as db:
        rows = db.execute(
            select(PolicyChunkRow, PolicyDocumentRow)
            .join(PolicyDocumentRow, PolicyDocumentRow.id == PolicyChunkRow.document_id)
            .where(PolicyChunkRow.id.in_(references))
        ).all()
    return [
        {
            "source": document.source_path,
            "section": chunk.section,
            "version": document.version,
            "excerpt": chunk.content[:360],
            "chunk_id": chunk.id,
            "retrieval_method": "checkpoint_reference_rehydration",
        }
        for chunk, document in rows
    ]


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
    ticket: dict[str, Any] | None = None,
    consultation_route: str | None = None,
    safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": next((event.get("trace_id") for event in trace if event.get("trace_id")), None),
        "task_status": task_status,
        "request_id": request.request_id if request else None,
        "pending_confirmation": request.model_dump() if request else None,
        "resolution_proposal": proposal,
        "eligibility_result": eligibility,
        "execution_result": execution_result,
        "failure_reason": failure_reason,
        "task_plan": task_plan or [],
        "ticket": ticket,
        "consultation_route": consultation_route,
        "safety": safety,
        "trace": trace,
        "tool_results": tool_results,
        "final_response": final_response,
        "metrics": _metrics(began, trace, tool_results),
    }


def _create_handoff(
    service: RetailService,
    sid: str,
    *,
    category: str,
    reason_code: str,
    summary: str,
    request: ExecutionRequestSummary | None = None,
    order_id: str | None = None,
    thread_id: str | None = None,
    outcome: dict[str, Any] | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    request_id = request.request_id if request else None
    bound_order_id = request.order_id if request else order_id
    projection = {
        "task_status": (outcome or {}).get("task_status"),
        "failure_reason": reason_code,
        "request_id": request_id,
        "order_id": bound_order_id,
    }
    return TicketService(service.engine).create(
        sid,
        category=category,
        severity="high" if category in {"high_risk", "execution_failed"} else "medium",
        priority=2 if category in {"high_risk", "execution_failed"} else 3,
        reason_code=reason_code,
        summary=summary,
        requested_action={
            "action": request.action_type if request else "human_review",
            "request_id": request_id,
            "order_id": bound_order_id,
        },
        idempotency_key=ticket_idempotency_key(
            sid,
            category,
            reason_code,
            request_id=request_id,
            thread_id=thread_id,
        ),
        actor=actor,
        order_id=bound_order_id,
        request_id=request_id,
        thread_id=thread_id,
        agent_state=projection,
    )


def _explicit_human_request(message: str) -> bool:
    return bool(HUMAN_REQUEST.search(message.strip()))


def _consultation_route(message: str, outcome: dict[str, Any]) -> str:
    status = outcome.get("task_status")
    if status in {
        "clarification",
        "needs_clarification",
        "triage_error",
        "route_limit",
        "resolution_failed",
    }:
        return "unclear"
    if status == "unsupported":
        return "out_of_scope" if OUT_OF_SCOPE.search(message) else "unclear"
    if status == "policy_failed":
        return "evidence_insufficient"
    if status == "query_failed":
        return "data_unavailable"
    if status in {
        "proposal_ready",
        "ineligible",
        "pending_confirmation",
        "confirmation_rejected",
        "executed",
        "execution_failed",
    }:
        return "after_sales"
    triage = outcome.get("triage") or {}
    intents = set(triage.get("intents") or [])
    if "policy_inquiry" in intents or status == "policy_answered":
        return "faq_policy"
    data = outcome.get("order_data") or {}
    if "product_inquiry" in intents or any(
        result.get("kind") == "product" for result in data.values()
    ):
        return "product"
    if "order_query" in intents or data:
        return "order_logistics"
    return "after_sales"


def _customer_response(outcome: dict[str, Any], route: str) -> str:
    status = outcome.get("task_status")
    if route == "faq_policy" and outcome.get("policy_context"):
        return policy_answer(outcome["policy_context"])
    if route in {"product", "order_logistics"} and outcome.get("order_data"):
        answer = query_answer(outcome["order_data"])
        if outcome.get("policy_context"):
            answer += "\n\n" + policy_answer(outcome["policy_context"])
        return answer
    if status in {"clarification", "needs_clarification", "triage_error"}:
        missing = outcome.get("missing_information") or []
        if missing:
            return clarification(missing)
        return (
            UNRESOLVED_NOTICE + "我还无法确定你要咨询的内容。请说明是商品、政策、订单物流，"
            "还是取消/退货需求。 " + HUMAN_SUGGESTION
        )
    if route == "out_of_scope":
        return (
            UNRESOLVED_NOTICE + "这个问题超出当前商店客服范围。我可以协助商品、政策、本人订单、"
            "物流、取消或退货。 " + HUMAN_SUGGESTION
        )
    if route == "unclear":
        return (
            UNRESOLVED_NOTICE + "我还无法确定你的诉求。请说明是咨询商品/政策、查订单/物流，"
            "还是申请取消/退货。 " + HUMAN_SUGGESTION
        )
    if route == "evidence_insufficient":
        return (
            UNRESOLVED_NOTICE + "当前没有检索到足够的政策依据，因此不会臆测结论或执行任何操作。"
            "请补充具体业务场景。 " + HUMAN_SUGGESTION
        )
    if route == "data_unavailable":
        errors = set(outcome.get("errors") or [])
        if "order_not_found" in errors:
            return (
                UNRESOLVED_NOTICE + "没有找到该订单，或它不属于当前账户。请核对订单号；"
                "未暴露其他客户数据。 " + HUMAN_SUGGESTION
            )
        return (
            UNRESOLVED_NOTICE + "当前业务数据暂时不可用，因此没有给出未核实结论，也没有执行"
            "任何写操作。请稍后重试。 " + HUMAN_SUGGESTION
        )
    if status == "ineligible":
        return (
            UNRESOLVED_NOTICE
            + "当前订单状态或请求参数不符合确定性业务规则，因此没有执行订单写入。 "
            + HUMAN_SUGGESTION
        )
    response = outcome.get("final_response")
    return response if isinstance(response, str) else "当前请求未完成，未执行订单写操作。"


def _same_action(
    message: str, request: ExecutionRequestSummary, thread_order_id: str | None = None
) -> bool:
    try:
        triage = MockTriage().classify(message)
    except ValueError:
        return False
    expected_order = triage.order_id or thread_order_id
    if expected_order != request.order_id:
        return False
    if request.action_type == "cancel":
        return "cancel_order" in triage.intents and triage.extracted_parameters.get(
            "reason"
        ) == request.proposed_parameters.get("reason")
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
    thread_key: str,
    request: ExecutionRequestSummary,
    engine: Any,
) -> AgentState:
    with store.lock:
        state = store.states[thread_key]
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
        store.states[thread_key] = deepcopy(updated)
        store.update_checkpoint(
            engine,
            thread_key,
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
        return updated


def _store_rejection(
    store: SessionStateStore,
    thread_key: str,
    request: ExecutionRequestSummary,
    confirmation: ConfirmationRecord,
    engine: Any,
) -> AgentState:
    with store.lock:
        state = store.states.get(thread_key)
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
        store.states[thread_key] = deepcopy(updated)
        store.update_checkpoint(
            engine,
            thread_key,
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
        return updated


def _failure(
    began: float,
    store: SessionStateStore,
    thread_key: str,
    request: ExecutionRequestSummary | None,
    error: BusinessError,
    service: RetailService,
) -> dict[str, Any]:
    response = "操作没有执行，订单没有被改动。"
    if error.code == "order_changed":
        response += " 订单状态已变化，请重新提交诉求以生成并确认新方案。"
    trace = [{"node": "supervisor_result", "status": "execution_failed", "code": error.code}]
    action = request.action_type if request else "unknown"
    tools = [{"tool": f"execute_{action}_controlled", "status": "error", "code": error.code}]
    response += " " + UNRESOLVED_NOTICE + HUMAN_SUGGESTION
    with store.lock:
        state = store.states.get(thread_key)
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
                store.states[thread_key] = deepcopy(updated)
                store.update_checkpoint(
                    service.engine,
                    thread_key,
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


def _scoped_request(
    execution: ExecutionService, sid: str, state: AgentState
) -> ExecutionRequestSummary | None:
    """Surface only the request stored in this thread's own checkpoint."""
    pending = state.get("execution_request")
    if pending is None:
        return None
    try:
        request = execution.get_request(sid, pending.request_id)
    except BusinessError:
        return None
    return (
        request
        if request.status in {"pending_confirmation", "confirmed", "executing"}
        else None
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
    thread: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one natural-language turn; confirmation decisions are deterministic."""
    began = perf_counter()
    phrase = message.strip()
    if not phrase:
        raise BusinessError("message_required")
    thread_id = thread["thread_id"] if thread else None
    thread_order_id = thread.get("order_id") if thread else None
    thread_key = thread_id or sid
    message_store = MessageStore(service.engine)
    with Session(service.engine) as db:
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        user_id = session.user_id

    safety = ContentSafetyChecker().check(phrase)
    current_route = "after_sales"
    safety_trace = {
        "node": "content_safety",
        "status": "allowed" if safety.allowed else "blocked",
        "code": safety.reason_code,
        "trace_id": uuid4().hex,
        "elapsed_ms": 0.0,
    }

    def finish(response: dict[str, Any]) -> dict[str, Any]:
        nonlocal current_route
        trace = response.get("trace")
        if not isinstance(trace, list):
            trace = []
        if not trace or trace[0].get("node") != "content_safety":
            if trace and trace[0].get("trace_id"):
                safety_trace["trace_id"] = trace[0]["trace_id"]
            response["trace"] = [safety_trace, *trace]
        response["trace_id"] = response.get("trace_id") or safety_trace["trace_id"]
        response["consultation_route"] = current_route
        response["safety"] = safety.model_dump()
        response["thread_id"] = thread_key
        response["thread_order_id"] = thread_order_id
        response["thread_kind"] = thread["kind"] if thread else "session"
        response["metrics"] = _metrics(
            began,
            response["trace"],
            response.get("tool_results") if isinstance(response.get("tool_results"), list) else [],
        )
        final = response.get("final_response")
        if isinstance(final, str) and final:
            message_store.append(
                sid,
                "assistant",
                final,
                meta={
                    "task_status": response.get("task_status"),
                    "consultation_route": current_route,
                    "safety_category": safety.category,
                },
                trace_id=response.get("trace_id"),
                thread_id=thread_id,
            )
        return response

    state, recovered = store.load(
        service.engine,
        thread_key,
        session_id=sid,
        user_id=user_id,
        messages=message_store.checkpoint_messages(sid, thread_id=thread_id),
    )
    active = _scoped_request(execution, sid, state) if user_id is not None else None
    if not safety.allowed:
        current_route = "content_blocked"
        return finish(
            _response(
                began,
                task_status="content_blocked",
                final_response=blocked_message(safety.category),
                trace=[],
                tool_results=[],
                request=active,
                failure_reason=safety.reason_code,
            )
        )

    message_store.append(
        sid,
        "user",
        message,
        meta={"source": "multi_agent_chat"},
        thread_id=thread_id,
    )
    messages = message_store.checkpoint_messages(sid, thread_id=thread_id)
    if recovered:
        store.update_checkpoint(service.engine, thread_key, {"messages": [messages[-1]]})

    if thread_order_id is not None:
        cross_orders = [
            value for value in mentioned_order_ids(phrase) if value != thread_order_id
        ]
        if cross_orders:
            current_route = "order_scope_mismatch"
            response = (
                f"当前对话已绑定订单 {thread_order_id}，不能在同一窗口处理其他订单。"
                "请在“我的订单”中打开目标订单的客服窗口后再继续。"
            )
            return finish(
                _response(
                    began,
                    task_status="order_scope_mismatch",
                    final_response=response,
                    trace=[],
                    tool_results=[],
                )
            )

    if _explicit_human_request(phrase):
        current_route = "human_handoff"
        order_match = ORDER_ID.search(phrase)
        ticket = _create_handoff(
            service,
            sid,
            category="customer_requested_human",
            reason_code="customer_requested_human",
            summary="客户明确要求转接人工客服。",
            request=active,
            order_id=thread_order_id if thread is not None else (
                order_match.group(1) if order_match else None
            ),
            thread_id=thread_id,
            actor="user",
        )
        response = f"已创建工单 {ticket['ticket_no']}，尚未处理完成。"
        trace = [
            {
                "node": "human_handoff",
                "status": "ticket_created",
                "trace_id": safety_trace["trace_id"],
            }
        ]
        store.update_checkpoint(
            service.engine,
            thread_key,
            {
                "task_status": "handoff_created",
                "next_agent": "end",
                "final_response": response,
                "messages": [AIMessage(content=response)],
                "trace": trace,
            },
        )
        return finish(
            _response(
                began,
                task_status="handoff_created",
                final_response=response,
                trace=trace,
                tool_results=[],
                request=active,
                ticket=ticket,
            )
        )
    if active is None and re.search(
        r"(?:^|：)\s*(?:不想取消了?|不取消了?|算了不取消了?)\s*[。！! ]*$", phrase
    ):
        response = "好的，已停止取消申请，订单未作修改。"
        with store.lock:
            state = store.states[thread_key]
            store.states[thread_key] = apply_agent_update(
                state,
                {
                    "triage_result": None,
                    "task_status": "confirmation_rejected",
                    "missing_information": [],
                    "routing_count": 0,
                    "final_response": response,
                    "messages": [AIMessage(content=response)],
                },
            )
            store.update_checkpoint(
                service.engine,
                thread_key,
                {
                    "triage_result": None,
                    "task_status": "confirmation_rejected",
                    "missing_information": [],
                    "routing_count": 0,
                    "final_response": response,
                    "messages": [AIMessage(content=response)],
                },
            )
        return finish(
            _response(
                began,
                task_status="confirmation_rejected",
                final_response=response,
                trace=[],
                tool_results=[],
            )
        )
    active_id = request_id or (active.request_id if active else None)
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
                    execution,
                    sid,
                    active_id,
                    request.idempotency_key,
                    store,
                    thread_id=thread_id,
                )
            except BusinessError as exc:
                return finish(_failure(began, store, thread_key, request, exc, service))
            return finish(
                _response(
                    began,
                    task_status=result["task_status"],
                    final_response=(
                        f"订单 {result['execution_result']['order_id']} 已完成处理，当前状态："
                        f"{status_label(result['execution_result']['after_status'])}。"
                        + (
                            "这只是本地退货申请，尚未发生真实退款。"
                            if request.action_type == "return"
                            else ""
                        )
                        if result["execution_result"]
                        and result["execution_result"]["status"] == "succeeded"
                        else "操作没有执行，请核对订单状态后重试。"
                    ),
                    trace=result["trace"],
                    tool_results=result["tool_results"],
                    request=execution.get_request(sid, active_id),
                    execution_result=result["execution_result"],
                    task_plan=result["task_plan"],
                )
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
                state = _store_rejection(
                    store, thread_key, request, confirmation, service.engine
                )
            except BusinessError as exc:
                return finish(_failure(began, store, thread_key, request, exc, service))
            trace = [{"node": "confirmation", "status": "rejected"}]
            tools = [{"tool": "confirmation_gate", "status": "error", "code": "rejected"}]
            return finish(
                _response(
                    began,
                    task_status="confirmation_rejected",
                    final_response="已拒绝本次方案，订单未作修改。",
                    trace=trace,
                    tool_results=tools,
                    request=request,
                    task_plan=[task.model_dump() for task in state["task_plan"]],
                )
            )
        if request.status == "pending_confirmation" and _same_action(
            phrase, request, thread_order_id
        ):
            waiting_response = f"该方案仍待确认：{request.summary}。请回复“确认”或“拒绝”。"
            store.update_checkpoint(
                service.engine,
                thread_key,
                {
                    "final_response": waiting_response,
                    "messages": [AIMessage(content=waiting_response)],
                    "trace": [{"node": "confirmation", "status": "waiting"}],
                },
            )
            return finish(
                _response(
                    began,
                    task_status="pending_confirmation",
                    final_response=waiting_response,
                    trace=[{"node": "confirmation", "status": "waiting"}],
                    tool_results=[],
                    request=request,
                )
            )
        execution.supersede_request(sid, active_id)

    outcome = run_turn(
        service,
        sid,
        phrase,
        (
            ThreadScopedTriage(MockTriage(), thread_order_id)
            if thread_order_id is not None
            else MockTriage()
        ),
        store,
        policy_agent=policy_agent,
        persist_messages=False,
        thread_id=thread_id,
    )
    current_route = _consultation_route(phrase, outcome)
    proposal = outcome["resolution_proposal"]
    eligibility = outcome["eligibility_result"]
    if (
        outcome["task_status"] == "proposal_ready"
        and proposal is not None
        and proposal["action_type"] in {"cancel", "return"}
        and eligibility is not None
    ):
        with store.lock:
            state = store.states[thread_key]
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
        state = _store_pending(store, thread_key, request, service.engine)
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
        return finish(
            _response(
                began,
                task_status="pending_confirmation",
                final_response=state["final_response"] or "方案待确认，订单尚未修改。",
                trace=trace,
                tool_results=outcome["tool_results"],
                request=request,
                proposal=proposal,
                eligibility=eligibility,
                task_plan=[task.model_dump() for task in state["task_plan"]],
            )
        )
    response = _customer_response(outcome, current_route)
    return finish(
        _response(
            began,
            task_status=outcome["task_status"],
            final_response=response,
            trace=outcome["trace"],
            tool_results=outcome["tool_results"],
            proposal=proposal,
            eligibility=eligibility,
            failure_reason=(outcome["errors"][-1] if outcome.get("errors") else None),
            task_plan=outcome["task_plan"],
        )
    )


# Backward-compatible import name retained for existing 2.5C callers.
run_cancel_conversation = run_after_sales_conversation


def current_task_progress(
    service: RetailService,
    execution: ExecutionService,
    sid: str,
    store: SessionStateStore,
    *,
    thread: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread_id = thread["thread_id"] if thread else None
    thread_key = thread_id or sid
    with Session(service.engine) as db:
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        if session.user_id is None:
            raise BusinessError("identity_required", 403)
    messages = MessageStore(service.engine).checkpoint_messages(sid, thread_id=thread_id)
    snapshot, recovered = store.load(
        service.engine,
        thread_key,
        session_id=sid,
        user_id=session.user_id,
        messages=messages,
    )
    if not recovered:
        raise BusinessError("task_state_not_found", 404)
    request = snapshot["execution_request"]
    persisted = execution.get_request(sid, request.request_id) if request else None
    policy_context = snapshot["policy_context"] or _rehydrate_policy_context(service, snapshot)
    return {
        "thread_id": snapshot["thread_id"],
        "thread_order_id": thread.get("order_id") if thread else None,
        "thread_kind": thread["kind"] if thread else "session",
        "task_status": snapshot["task_status"],
        "current_task": snapshot["current_task"],
        "task_plan": [task.model_dump() for task in snapshot["task_plan"]],
        "order_context": snapshot["order_context"],
        "policy_context": policy_context,
        "resolution_proposal": (
            snapshot["resolution_proposal"].model_dump()
            if snapshot["resolution_proposal"]
            else None
        ),
        "eligibility_result": (
            snapshot["eligibility_result"].model_dump() if snapshot["eligibility_result"] else None
        ),
        "pending_confirmation": persisted.model_dump() if persisted else None,
        "execution_result": (
            snapshot["execution_result"].model_dump() if snapshot["execution_result"] else None
        ),
        "trace": snapshot["trace"],
        "final_response": snapshot["final_response"],
    }
