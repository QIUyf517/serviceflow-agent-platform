from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import ChatTraceRow, engine_for
from app.llm import OpenAICompatibleProvider, ProviderError
from app.service import Action, BusinessError, RetailService

app = FastAPI(title="ServiceFlow", version="0.2.0")


class Health(BaseModel):
    status: str


@app.get("/api/v1/health", response_model=Health)
def health() -> Health:
    """Process liveness only; does not claim database readiness."""
    return Health(status="ok")


@lru_cache
def get_service() -> RetailService:
    return RetailService(engine_for(Settings().database_url))


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


@app.post("/api/v1/operations")
def propose(
    action: Action, sid: str = Depends(session_id), service: RetailService = Depends(get_service)
) -> dict[str, Any]:
    return service.propose(sid, action)


@app.post("/api/v1/operations/{proposal_id}/confirm")
def confirm(
    proposal_id: str,
    confirmation: Confirmation,
    sid: str = Depends(session_id),
    service: RetailService = Depends(get_service),
) -> dict[str, Any]:
    return service.confirm(sid, proposal_id, confirmed=confirmation.confirmed)


class ChatRequest(BaseModel):
    message: str
    proposal_id: str | None = None


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
