import secrets
from functools import lru_cache
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import ChatTraceRow, SessionRow, engine_for
from app.llm import OpenAICompatibleProvider, ProviderError
from app.multi_agent.execution import ExecutionService
from app.multi_agent.message_store import MessageStore
from app.multi_agent.workflow import SessionStateStore
from app.service import Action, BusinessError, CheckoutRequest, RetailService
from app.support_threads import SupportThreadService
from app.ticketing import TicketService

app = FastAPI(title="ServiceFlow", version="0.3.0")

phase22_store = SessionStateStore()


def _load_multi_agent_state(
    service: RetailService, sid: str, thread: dict[str, Any] | None = None
):
    """Recover state by server-owned session and thread; never accept a client thread ID."""
    with Session(service.engine) as db:
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        user_id = session.user_id
    thread_id = thread["thread_id"] if thread else None
    messages = MessageStore(service.engine).checkpoint_messages(sid, thread_id=thread_id)
    state, _ = phase22_store.load(
        service.engine,
        thread_id or sid,
        session_id=sid,
        user_id=user_id,
        messages=messages,
    )
    return state


class Health(BaseModel):
    status: str


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    """Process liveness only; does not claim database readiness."""
    return Health(status="ok")


@lru_cache
def get_service() -> RetailService:
    return RetailService(engine_for(Settings().database_url))


def get_execution_service(
    service: RetailService = Depends(get_service),
) -> ExecutionService:
    return ExecutionService(service.engine)


def get_ticket_service(
    service: RetailService = Depends(get_service),
) -> TicketService:
    return TicketService(service.engine)


def get_thread_service(
    service: RetailService = Depends(get_service),
) -> SupportThreadService:
    return SupportThreadService(service.engine)


def _resolve_thread(
    threads: SupportThreadService, sid: str, order_id: str | None
) -> dict[str, Any]:
    """Resolve the server-owned thread; the client never supplies a thread ID."""
    return threads.resolve(sid, order_id)


def operator_identity(
    x_operator_token: str | None = Header(default=None),
) -> str:
    """Demo-only operator auth, deliberately independent of customer sessions."""
    settings = Settings()
    configured = settings.operator_demo_token
    if configured is None:
        raise BusinessError("operator_auth_not_configured", 503)
    if x_operator_token is None or not secrets.compare_digest(
        x_operator_token,
        configured.get_secret_value(),
    ):
        raise BusinessError("operator_unauthorized", 401)
    return settings.operator_demo_id


@app.exception_handler(BusinessError)
def business_error(_request: Any, exc: BusinessError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code}})


@app.exception_handler(SQLAlchemyError)
def database_error(_request: Any, _exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable"}})


@app.exception_handler(ProviderError)
def provider_error(_request: Any, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": {"code": str(exc)}})


def session_id(x_session_id: str = Header()) -> str:
    return x_session_id


class Identity(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    zip_code: str | None = None


class Confirmation(BaseModel):
    confirmed: bool


@app.post("/api/v1/sessions")
def start(service: RetailService = Depends(get_service)) -> dict[str, str]:
    return {"session_id": service.start()}


@app.post("/api/v1/sessions/{sid}/verify")
def verify(
    sid: str, identity: Identity, service: RetailService = Depends(get_service)
) -> dict[str, str]:
    return {"user_id": service.verify(sid, **identity.model_dump())}


@app.get("/api/v1/users/me")
def user(
    sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.user(sid)


@app.get("/api/v1/customer/conversation")
def customer_conversation(
    order_id: str | None = None,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
) -> list[dict[str, Any]]:
    # The session is only a bearer handle; require its server-side identity binding.
    with Session(service.engine) as db:
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        if session.user_id is None:
            raise BusinessError("identity_required", 403)
    thread = SupportThreadService(service.engine).resolve(sid, order_id)
    return [
        {
            "sequence": row.sequence,
            "role": row.role,
            "content": row.content,
            "thread_id": row.thread_id,
            "created_at": row.created_at,
        }
        for row in MessageStore(service.engine).rows(sid, thread_id=thread["thread_id"])
        if row.role in {"user", "assistant", "operator"}
    ]


@app.get("/api/v1/orders")
def orders(
    sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> list[dict[str, Any]]:
    return service.orders(sid)


@app.post("/api/v1/orders")
def checkout(
    request: CheckoutRequest,
    sid: str = Depends(session_id),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    service: RetailService = Depends(get_service),
) -> dict[str, Any]:
    return service.checkout(sid, request, idempotency_key=idempotency_key)


@app.get("/api/v1/orders/{oid}")
def order(
    oid: str, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.order(sid, oid)


@app.get("/api/v1/products")
def products(
    sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> list[dict[str, Any]]:
    return service.products(sid)


@app.get("/api/v1/products/{pid}")
def product(
    pid: str, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.product(sid, pid, public=True)


@app.post("/api/v1/operations", deprecated=True)
def propose(
    action: Action, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    del action, sid, service
    raise BusinessError("legacy_write_api_disabled_use_multi_agent", 410)


@app.post("/api/v1/operations/{proposal_id}/confirm", deprecated=True)
def confirm(
    proposal_id: str,
    confirmation: Confirmation,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
) -> dict[str, Any]:
    del proposal_id, confirmation, sid, service
    raise BusinessError("legacy_write_api_disabled_use_multi_agent", 410)


class ChatRequest(BaseModel):
    message: str
    proposal_id: str | None = None


class PlanRequest(BaseModel):
    message: str


class CancelExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proposal_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^\S+$")


class ConfirmationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["confirm", "reject"]
    confirmation_text: str = Field(min_length=1, max_length=500)


class MultiAgentConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    order_id: str | None = Field(default=None, min_length=1, max_length=128)


class SupportThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str | None = Field(default=None, min_length=1, max_length=128)


class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal["customer_requested_human"] = "customer_requested_human"
    severity: str = Field(default="medium", min_length=1, max_length=32)
    priority: int = Field(default=3, ge=1, le=5)
    reason_code: str = Field(default="customer_requested_human", min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=1_000)
    requested_action: dict[str, Any] = Field(default_factory=dict)
    order_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class TicketAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assignee: str = Field(min_length=1, max_length=128)


class TicketReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=2_000)


class TicketStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "open",
        "assigned",
        "in_progress",
        "waiting_customer",
        "resolved",
        "closed",
        "cancelled",
    ]
    close_reason: (
        Literal[
            "resolved_by_agent",
            "resolved_by_operator",
            "customer_unresponsive",
            "duplicate",
            "rejected",
            "out_of_scope",
        ]
        | None
    ) = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    proposed_params: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = Field(default=None, ge=1, le=604_800)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=1_000)


@app.post("/api/v1/support/threads")
def open_support_thread(
    request: SupportThreadRequest,
    sid: str = Depends(session_id),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    """Create or restore one order's conversation thread after an ownership check."""
    return _resolve_thread(threads, sid, request.order_id)


@app.post("/api/v1/tickets")
def create_ticket(
    request: TicketCreateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    sid: str = Depends(session_id),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    """Customer-visible handoff registration; it does not claim work is completed."""
    result = tickets.create(
        sid,
        category=request.category,
        severity=request.severity,
        priority=request.priority,
        reason_code=request.reason_code,
        summary=request.summary,
        requested_action=request.requested_action,
        idempotency_key=idempotency_key,
        actor="user",
        order_id=request.order_id,
        request_id=request.request_id,
        thread_id=request.thread_id,
        agent_state={"source": "explicit_customer_request"},
        customer_explicit=True,
    )
    result["message"] = f"已创建工单 {result['ticket_no']}，尚未处理完成。"
    return result


@app.get("/api/v1/tickets")
def list_tickets(
    status: str | None = None,
    category: str | None = None,
    assignee: str | None = None,
    created_from: int | None = None,
    created_to: int | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.list(
        status=status,
        category=category,
        assignee=assignee,
        created_from=created_from,
        created_to=created_to,
        offset=offset,
        limit=limit,
    )


@app.get("/api/v1/customer/tickets")
def customer_tickets(
    sid: str = Depends(session_id), tickets: TicketService = Depends(get_ticket_service)
) -> list[dict[str, Any]]:
    return tickets.customer_tickets(sid)


@app.get("/api/v1/customer/tickets/{ticket_id}/updates")
def customer_ticket_updates(
    ticket_id: str,
    sid: str = Depends(session_id),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.customer_updates(sid, ticket_id)


@app.post("/api/v1/customer/tickets/{ticket_id}/messages")
def customer_ticket_reply(
    ticket_id: str,
    request: TicketReplyRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    sid: str = Depends(session_id),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    """Send a customer message to the bound human ticket without invoking an Agent."""
    return tickets.customer_reply(sid, ticket_id, request.content, idempotency_key)


@app.get("/api/v1/tickets/{ticket_id}")
def ticket_detail(
    ticket_id: str,
    _operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.detail(ticket_id)


@app.post("/api/v1/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: str,
    request: TicketAssignRequest,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.assign(ticket_id, request.assignee, operator_id)


@app.post("/api/v1/tickets/{ticket_id}/reply")
def reply_ticket(
    ticket_id: str,
    request: TicketReplyRequest,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.reply(ticket_id, request.content, operator_id)


@app.post("/api/v1/tickets/{ticket_id}/status")
def change_ticket_status(
    ticket_id: str,
    request: TicketStatusRequest,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.change_status(
        ticket_id,
        request.status,
        operator_id,
        close_reason=request.close_reason,
    )


@app.post("/api/v1/tickets/{ticket_id}/approvals")
def request_ticket_approval(
    ticket_id: str,
    request: ApprovalRequest,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    settings = Settings()
    return tickets.request_approval(
        ticket_id,
        request_id=request.request_id,
        action=request.action,
        proposed_params=request.proposed_params,
        operator_id=operator_id,
        ttl_seconds=request.ttl_seconds or settings.approval_ttl_seconds,
    )


@app.post("/api/v1/tickets/{ticket_id}/approvals/{approval_id}/decision")
def decide_ticket_approval(
    ticket_id: str,
    approval_id: str,
    request: ApprovalDecisionRequest,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return tickets.decide_approval(
        ticket_id,
        approval_id,
        decision=request.decision,
        reason=request.reason,
        operator_id=operator_id,
    )


@app.get("/api/v1/tickets/{ticket_id}/audit")
def ticket_audit(
    ticket_id: str,
    _operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
) -> dict[str, Any]:
    return {"ticket_id": ticket_id, "events": tickets.audit(ticket_id)}


@app.post("/api/v1/tickets/{ticket_id}/execute")
def operator_trigger_execution(
    ticket_id: str,
    operator_id: str = Depends(operator_identity),
    tickets: TicketService = Depends(get_ticket_service),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    """Trigger the existing executor; operator approval is not customer consent."""
    sid, request_id, _action, idempotency_key = tickets.approved_execution_binding(
        ticket_id,
        operator_id,
    )
    return execution.execute_action(
        sid,
        request_id,
        idempotency_key=idempotency_key,
    ).model_dump()


@app.post("/api/v1/debug/plan")
def debug_plan(
    request: PlanRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
) -> dict[str, Any]:
    """Read-only multi-agent flow; Resolution validates but cannot write business data."""
    from app.multi_agent.policy_agent import LLMPolicyAnswerer, build_policy_agent
    from app.multi_agent.triage import LLMTriage, MockTriage
    from app.multi_agent.workflow import run_turn

    if not request.message.strip():
        raise HTTPException(422, detail="message_required")
    settings = Settings()
    if settings.agent_provider == "mock":
        triage = MockTriage()
        answerer = None
    else:
        provider = OpenAICompatibleProvider(settings)
        triage = LLMTriage(provider)
        answerer = LLMPolicyAnswerer(provider)
    policy_agent = build_policy_agent(service.engine, settings, answerer=answerer)
    return run_turn(
        service,
        sid,
        request.message,
        triage,
        phase22_store,
        policy_agent=policy_agent,
        thread_id=SupportThreadService(service.engine).resolve(sid, None)["thread_id"],
    )


@app.post("/api/v1/multi-agent/chat")
def multi_agent_chat(
    request: MultiAgentConversationRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    """Natural-language cancel/return flow; confirmation parsing is deterministic."""
    from app.multi_agent.conversation import run_after_sales_conversation
    from app.multi_agent.policy_agent import build_policy_agent

    local_settings = Settings(
        _env_file=None,
        agent_provider="mock",
        policy_retrieval_strategy="keyword",
        policy_top_k=Settings().policy_top_k,
        policy_embedding_api_key=None,
    )
    policy_agent = build_policy_agent(service.engine, local_settings)
    thread = _resolve_thread(threads, sid, request.order_id)
    return run_after_sales_conversation(
        service,
        execution,
        sid,
        request.message,
        phase22_store,
        policy_agent,
        request_id=request.request_id,
        thread=thread,
    )


@app.post("/api/v1/single-agent/controlled-chat")
def controlled_single_agent_chat(
    request: MultiAgentConversationRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    """Safe product baseline sharing confirmation, rules, transactions and audit."""
    from app.multi_agent.policy_agent import build_policy_agent
    from app.single_agent_controlled import run_controlled_single_agent

    settings = Settings(
        _env_file=None,
        agent_provider="mock",
        policy_retrieval_strategy="keyword",
        policy_embedding_api_key=None,
    )
    return run_controlled_single_agent(
        service,
        execution,
        build_policy_agent(service.engine, settings),
        sid,
        request.message,
        request_id=request.request_id,
    )


@app.get("/api/v1/multi-agent/tasks/current")
def current_multi_agent_task(
    order_id: str | None = None,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    from app.multi_agent.conversation import current_task_progress

    thread = _resolve_thread(threads, sid, order_id)
    return current_task_progress(service, execution, sid, phase22_store, thread=thread)


@app.post("/api/v1/multi-agent/cancel-requests")
def create_cancel_request(
    request: CancelExecutionRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    """Materialize the current eligible Resolution proposal; do not change the order."""
    with phase22_store.lock:
        state = _load_multi_agent_state(
            service, sid, _resolve_thread(threads, sid, None)
        )
        proposal = state["resolution_proposal"]
        eligibility = state["eligibility_result"]
        if proposal is None or eligibility is None or proposal.proposal_id != request.proposal_id:
            raise BusinessError("resolution_proposal_not_found", 404)
        proposal = proposal.model_copy(deep=True)
        eligibility = eligibility.model_copy(deep=True)
    return execution.prepare_cancel(
        sid, proposal, eligibility, request.idempotency_key
    ).model_dump()


@app.get("/api/v1/multi-agent/cancel-requests/{request_id}")
def get_cancel_request(
    request_id: str,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    return execution.get_request(sid, request_id).model_dump()


@app.post("/api/v1/multi-agent/cancel-requests/{request_id}/decisions")
def decide_cancel_request(
    request_id: str,
    decision: ConfirmationDecision,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    return execution.record_decision(
        sid,
        request_id,
        decision=decision.decision,
        confirmation_text=decision.confirmation_text,
    ).model_dump()


@app.post("/api/v1/multi-agent/cancel-requests/{request_id}/execute")
def execute_cancel_request(
    request_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    from app.multi_agent.workflow import run_execution_turn

    thread = _resolve_thread(threads, sid, None)
    return run_execution_turn(
        execution,
        sid,
        request_id,
        idempotency_key,
        phase22_store,
        thread_id=thread["thread_id"],
    )


@app.get("/api/v1/multi-agent/cancel-requests/{request_id}/audit")
def cancel_request_audit(
    request_id: str,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    return {"request_id": request_id, "events": execution.audit_events(sid, request_id)}


@app.post("/api/v1/multi-agent/return-requests")
def create_return_request(
    request: CancelExecutionRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    """Materialize the current eligible return proposal without changing the order."""
    with phase22_store.lock:
        state = _load_multi_agent_state(
            service, sid, _resolve_thread(threads, sid, None)
        )
        proposal = state["resolution_proposal"]
        eligibility = state["eligibility_result"]
        if (
            proposal is None
            or eligibility is None
            or proposal.action_type != "return"
            or proposal.proposal_id != request.proposal_id
        ):
            raise BusinessError("resolution_proposal_not_found", 404)
        proposal = proposal.model_copy(deep=True)
        eligibility = eligibility.model_copy(deep=True)
    return execution.prepare_return(
        sid, proposal, eligibility, request.idempotency_key
    ).model_dump()


@app.get("/api/v1/multi-agent/return-requests/{request_id}")
def get_return_request(
    request_id: str,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    result = execution.get_request(sid, request_id)
    if result.action_type != "return":
        raise BusinessError("execution_action_mismatch", 409)
    return result.model_dump()


@app.post("/api/v1/multi-agent/return-requests/{request_id}/decisions")
def decide_return_request(
    request_id: str,
    decision: ConfirmationDecision,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    request = execution.get_request(sid, request_id)
    if request.action_type != "return":
        raise BusinessError("execution_action_mismatch", 409)
    return execution.record_decision(
        sid,
        request_id,
        decision=decision.decision,
        confirmation_text=decision.confirmation_text,
    ).model_dump()


@app.post("/api/v1/multi-agent/return-requests/{request_id}/execute")
def execute_return_request(
    request_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
    threads: SupportThreadService = Depends(get_thread_service),
) -> dict[str, Any]:
    from app.multi_agent.workflow import run_execution_turn

    request = execution.get_request(sid, request_id)
    if request.action_type != "return":
        raise BusinessError("execution_action_mismatch", 409)
    thread = _resolve_thread(threads, sid, None)
    return run_execution_turn(
        execution,
        sid,
        request_id,
        idempotency_key,
        phase22_store,
        thread_id=thread["thread_id"],
    )


@app.get("/api/v1/multi-agent/return-requests/{request_id}/audit")
def return_request_audit(
    request_id: str,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    request = execution.get_request(sid, request_id)
    if request.action_type != "return":
        raise BusinessError("execution_action_mismatch", 409)
    return {"request_id": request_id, "events": execution.audit_events(sid, request_id)}


@app.post("/api/v1/chat")
def chat(
    request: ChatRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
) -> dict[str, Any]:
    from app.agent import chat_once
    from app.live_agent import live_chat

    if not request.message.strip():
        raise HTTPException(422, detail="message_required")
    if request.proposal_id is not None:
        raise BusinessError("legacy_chat_write_disabled_use_multi_agent", 410)
    settings = Settings()
    if settings.agent_provider == "mock":
        return chat_once(service, sid, request.message, request.proposal_id)
    provider = OpenAICompatibleProvider(settings)
    return live_chat(
        service,
        sid,
        request.message,
        request.proposal_id,
        provider,
        max_tool_calls=settings.agent_max_tool_calls,
    )


@app.get("/api/v1/traces/{trace_id}")
def trace(
    trace_id: str, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    with Session(service.engine) as db:
        row = db.scalar(
            select(ChatTraceRow).where(ChatTraceRow.id == trace_id, ChatTraceRow.session_id == sid)
        )
        if row is None:
            raise BusinessError("trace_not_found", 404)
        return {
            "trace_id": trace_id,
            "events": row.events,
            "elapsed_ms": row.elapsed_ms,
            "token_usage": row.token_usage,
        }
