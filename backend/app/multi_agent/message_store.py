"""Normalized, transactionally sequenced conversation messages."""

from __future__ import annotations

import re
from time import time
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database import MessageRow, SessionRow
from app.service import BusinessError

MessageRole = Literal["user", "assistant", "system", "operator"]

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SECRET = re.compile(r"(?i)\b(?:sk|api)[-_][A-Z0-9_-]{12,}\b")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
_ADDRESS = re.compile(
    r"(?i)\b(address|shipping_address|billing_address)\s*[:=]\s*.*?"
    r"(?=\s+(?:card_number|cvv|cvc|security_code)\s*[:=]|[;\n]|$)"
)
_PAYMENT_CREDENTIAL = re.compile(
    r"(?i)\b(card_number|cvv|cvc|security_code)\s*[:=]\s*[^,;\s]+"
)


def redact_checkpoint_content(content: str) -> str:
    """Remove credentials and direct identifiers before LangGraph persistence."""
    redacted = _EMAIL.sub("[REDACTED_EMAIL]", content)
    redacted = _SECRET.sub("[REDACTED_SECRET]", redacted)
    redacted = _CARD.sub("[REDACTED_PAYMENT]", redacted)
    redacted = _ADDRESS.sub(r"\1=[REDACTED_ADDRESS]", redacted)
    return _PAYMENT_CREDENTIAL.sub(r"\1=[REDACTED_PAYMENT]", redacted)


class MessageStore:
    """Persist messages without treating them as identity or authorization evidence."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        meta: dict[str, Any] | None = None,
        trace_id: str | None = None,
        ticket_id: str | None = None,
    ) -> int:
        if not content.strip():
            raise ValueError("message_content_required")
        with Session(self.engine) as db, db.begin():
            session = db.scalar(
                select(SessionRow).where(SessionRow.id == session_id).with_for_update()
            )
            if session is None:
                raise BusinessError("session_not_found", 404)
            sequence = (
                db.scalar(
                    select(func.max(MessageRow.sequence)).where(
                        MessageRow.session_id == session_id
                    )
                )
                or 0
            ) + 1
            db.add(
                MessageRow(
                    id=uuid4().hex,
                    session_id=session_id,
                    ticket_id=ticket_id,
                    role=role,
                    content=content,
                    meta=meta or {},
                    trace_id=trace_id,
                    sequence=sequence,
                    created_at=int(time()),
                )
            )
            return sequence

    def rows(self, session_id: str, *, limit: int = 200) -> list[MessageRow]:
        if limit < 1 or limit > 500:
            raise ValueError("message_limit_invalid")
        with Session(self.engine) as db:
            if db.get(SessionRow, session_id) is None:
                raise BusinessError("session_not_found", 404)
            rows = db.scalars(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.sequence.desc())
                .limit(limit)
            ).all()
            return list(reversed(rows))

    def langchain_messages(self, session_id: str, *, limit: int = 200) -> list[AnyMessage]:
        messages: list[AnyMessage] = []
        for row in self.rows(session_id, limit=limit):
            if row.role == "user":
                messages.append(HumanMessage(content=row.content))
            elif row.role == "assistant":
                messages.append(AIMessage(content=row.content))
            elif row.role == "system":
                messages.append(SystemMessage(content=row.content))
            else:
                messages.append(ChatMessage(role="operator", content=row.content))
        return messages

    def checkpoint_messages(self, session_id: str, *, limit: int = 200) -> list[AnyMessage]:
        """Return a redacted projection safe for checkpoint serialization."""
        projected: list[AnyMessage] = []
        for message in self.langchain_messages(session_id, limit=limit):
            content = (
                redact_checkpoint_content(message.content)
                if isinstance(message.content, str)
                else "[REDACTED_NON_TEXT_MESSAGE]"
            )
            if isinstance(message, HumanMessage):
                projected.append(HumanMessage(content=content))
            elif isinstance(message, AIMessage):
                projected.append(AIMessage(content=content))
            elif isinstance(message, SystemMessage):
                projected.append(SystemMessage(content=content))
            else:
                projected.append(ChatMessage(role="operator", content=content))
        return projected
