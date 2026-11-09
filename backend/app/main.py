from functools import lru_cache
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import ChatTraceRow, engine_for
from app.llm import OpenAICompatibleProvider, ProviderError
from app.multi_agent.execution import ExecutionService
from app.multi_agent.workflow import SessionStateStore
from app.service import Action, BusinessError, RetailService

app = FastAPI(title="ServiceFlow", version="0.2.7")

phase22_store = SessionStateStore()


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


@app.get("/api/v1/orders")
def orders(
    sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> list[dict[str, Any]]:
    return service.orders(sid)


@app.get("/api/v1/orders/{oid}")
def order(
    oid: str, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.order(sid, oid)


@app.get("/api/v1/products/{pid}")
def product(
    pid: str, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.product(sid, pid)


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
    )


@app.post("/api/v1/multi-agent/chat")
def multi_agent_chat(
    request: MultiAgentConversationRequest,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
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
    return run_after_sales_conversation(
        service,
        execution,
        sid,
        request.message,
        phase22_store,
        policy_agent,
        request_id=request.request_id,
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
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    from app.multi_agent.conversation import current_task_progress

    return current_task_progress(service, execution, sid, phase22_store)


@app.post("/api/v1/multi-agent/cancel-requests")
def create_cancel_request(
    request: CancelExecutionRequest,
    sid: str = Depends(session_id),
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    """Materialize the current eligible Resolution proposal; do not change the order."""
    with phase22_store.lock:
        state = phase22_store.states.get(sid)
        proposal = state["resolution_proposal"] if state else None
        eligibility = state["eligibility_result"] if state else None
        if (
            proposal is None
            or eligibility is None
            or proposal.proposal_id != request.proposal_id
        ):
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
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    from app.multi_agent.workflow import run_execution_turn

    return run_execution_turn(
        execution, sid, request_id, idempotency_key, phase22_store
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
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    """Materialize the current eligible return proposal without changing the order."""
    with phase22_store.lock:
        state = phase22_store.states.get(sid)
        proposal = state["resolution_proposal"] if state else None
        eligibility = state["eligibility_result"] if state else None
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
    execution: ExecutionService = Depends(get_execution_service),
) -> dict[str, Any]:
    from app.multi_agent.workflow import run_execution_turn

    request = execution.get_request(sid, request_id)
    if request.action_type != "return":
        raise BusinessError("execution_action_mismatch", 409)
    return run_execution_turn(
        execution, sid, request_id, idempotency_key, phase22_store
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
