"""Deterministic ticket, approval, and human-handoff service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import time
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    ApprovalRow,
    AuditEventRow,
    Base,
    ExecutionRequestRow,
    MessageRow,
    OrderRow,
    SessionRow,
    TicketRow,
)
from app.multi_agent.message_store import redact_checkpoint_content
from app.service import BusinessError

TicketCategory = Literal[
    "unsupported_request",
    "high_risk",
    "rule_conflict",
    "execution_failed",
    "clarification_exhausted",
    "customer_requested_human",
]
TicketActor = Literal["user", "agent", "operator", "system"]

TICKET_CATEGORIES = {
    "unsupported_request",
    "high_risk",
    "rule_conflict",
    "execution_failed",
    "clarification_exhausted",
    "customer_requested_human",
}
TICKET_STATUSES = {
    "open",
    "assigned",
    "in_progress",
    "waiting_customer",
    "resolved",
    "closed",
    "cancelled",
}
CLOSE_REASONS = {
    "resolved_by_agent",
    "resolved_by_operator",
    "customer_unresponsive",
    "duplicate",
    "rejected",
    "out_of_scope",
}
STATUS_TRANSITIONS = {
    "open": {"assigned", "cancelled"},
    "assigned": {"in_progress", "cancelled"},
    "in_progress": {"waiting_customer", "resolved", "cancelled"},
    "waiting_customer": {"in_progress", "resolved", "cancelled"},
    "resolved": {"in_progress", "closed"},
    "closed": set(),
    "cancelled": set(),
}
_SENSITIVE_KEYS = {
    "address",
    "billing_address",
    "card",
    "card_number",
    "cvc",
    "cvv",
    "email",
    "name",
    "payment_credential",
    "phone",
    "security_code",
    "shipping_address",
    "zip",
    "zip_code",
}


def sanitize_ticket_payload(value: Any) -> Any:
    """Return a bounded privacy-safe projection for tickets and unified audit."""
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).casefold() in _SENSITIVE_KEYS
                else sanitize_ticket_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_ticket_payload(item) for item in value[:50]]
    if isinstance(value, str):
        return redact_checkpoint_content(value)[:2_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def ticket_idempotency_key(
    session_id: str,
    category: str,
    reason_code: str,
    *,
    request_id: str | None = None,
) -> str:
    material = f"{session_id}\0{category}\0{reason_code}\0{request_id or ''}"
    return "ticket-" + hashlib.sha256(material.encode()).hexdigest()


class TicketService:
    """Server-owned ticket state machine; no LLM authority is accepted here."""

    def __init__(self, engine: Engine, *, clock: Callable[[], float] = time) -> None:
        self.engine = engine
        self.clock = clock
        Base.metadata.create_all(engine)

    @staticmethod
    def _audit(
        db: Session,
        ticket: TicketRow,
        event_type: str,
        actor: TicketActor,
        payload: dict[str, Any],
        *,
        created_at: int,
    ) -> None:
        db.add(
            AuditEventRow(
                id=uuid4().hex,
                event_type=event_type,
                session_id=ticket.session_id,
                ticket_id=ticket.id,
                request_id=ticket.request_id,
                order_id=ticket.order_id,
                actor=actor,
                payload=sanitize_ticket_payload(payload),
                created_at=created_at,
            )
        )

    @staticmethod
    def _ticket(ticket: TicketRow) -> dict[str, Any]:
        return {
            "id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "session_id": ticket.session_id,
            "user_id": ticket.user_id,
            "order_id": ticket.order_id,
            "request_id": ticket.request_id,
            "category": ticket.category,
            "severity": ticket.severity,
            "priority": ticket.priority,
            "status": ticket.status,
            "reason_code": ticket.reason_code,
            "summary": ticket.summary,
            "requested_action": ticket.requested_action,
            "agent_state_digest": ticket.agent_state_digest,
            "assignee": ticket.assignee,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "closed_at": ticket.closed_at,
            "close_reason": ticket.close_reason,
        }

    @staticmethod
    def _approval(approval: ApprovalRow) -> dict[str, Any]:
        return {
            "id": approval.id,
            "ticket_id": approval.ticket_id,
            "request_id": approval.request_id,
            "action": approval.action,
            "proposed_params": approval.proposed_params,
            "status": approval.status,
            "operator_id": approval.operator_id,
            "decision_reason": approval.decision_reason,
            "created_at": approval.created_at,
            "decided_at": approval.decided_at,
            "expires_at": approval.expires_at,
        }

    @staticmethod
    def _get_ticket(db: Session, ticket_id: str, *, lock: bool = False) -> TicketRow:
        statement = select(TicketRow).where(TicketRow.id == ticket_id)
        if lock:
            statement = statement.with_for_update()
        ticket = db.scalar(statement)
        if ticket is None:
            raise BusinessError("ticket_not_found", 404)
        return ticket

    def create(
        self,
        session_id: str,
        *,
        category: TicketCategory,
        severity: str,
        priority: int,
        reason_code: str,
        summary: str,
        requested_action: dict[str, Any],
        idempotency_key: str,
        actor: TicketActor,
        order_id: str | None = None,
        request_id: str | None = None,
        agent_state: dict[str, Any] | None = None,
        customer_explicit: bool = False,
    ) -> dict[str, Any]:
        if category not in TICKET_CATEGORIES:
            raise BusinessError("ticket_category_invalid", 422)
        if customer_explicit and category != "customer_requested_human":
            raise BusinessError("customer_ticket_category_forbidden", 403)
        if not 1 <= priority <= 5:
            raise BusinessError("ticket_priority_invalid", 422)
        if not severity or len(severity) > 32:
            raise BusinessError("ticket_severity_invalid", 422)
        if not reason_code.strip() or len(reason_code) > 128:
            raise BusinessError("ticket_reason_invalid", 422)
        if not summary.strip():
            raise BusinessError("ticket_summary_required", 422)
        if not 16 <= len(idempotency_key) <= 128 or any(
            char.isspace() for char in idempotency_key
        ):
            raise BusinessError("ticket_idempotency_key_invalid", 422)
        safe_summary = redact_checkpoint_content(summary.strip())[:1_000]
        safe_action = sanitize_ticket_payload(requested_action)
        digest_payload = sanitize_ticket_payload(agent_state or {})
        digest = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        now = int(self.clock())
        ticket = TicketRow(
            id=uuid4().hex,
            ticket_no=(
                "SF-"
                + datetime.fromtimestamp(now, UTC).strftime("%Y%m%d")
                + "-"
                + uuid4().hex[:10].upper()
            ),
            session_id=session_id,
            user_id=None,
            order_id=order_id,
            request_id=request_id,
            category=category,
            severity=severity,
            priority=priority,
            status="open",
            reason_code=reason_code,
            summary=safe_summary,
            requested_action=safe_action,
            agent_state_digest=digest,
            assignee=None,
            created_at=now,
            updated_at=now,
            closed_at=None,
            close_reason=None,
            idempotency_key=idempotency_key,
        )
        try:
            with Session(self.engine) as db, db.begin():
                session = db.scalar(
                    select(SessionRow)
                    .where(SessionRow.id == session_id)
                    .with_for_update()
                )
                if session is None:
                    raise BusinessError("session_not_found", 404)
                existing = db.scalar(
                    select(TicketRow).where(
                        TicketRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    if existing.session_id != session_id:
                        raise BusinessError("ticket_idempotency_key_conflict", 409)
                    result = self._ticket(existing)
                    result["idempotent_replay"] = True
                    return result
                request = None
                if request_id is not None:
                    request = db.get(ExecutionRequestRow, request_id)
                    if request is None or request.session_id != session_id:
                        raise BusinessError("execution_request_not_found", 404)
                    if request.user_id != session.user_id:
                        raise BusinessError("execution_request_not_found", 404)
                    if order_id is not None and order_id != request.order_id:
                        raise BusinessError("ticket_request_binding_invalid", 409)
                    ticket.order_id = request.order_id
                if ticket.order_id is not None:
                    if session.user_id is None:
                        raise BusinessError("identity_required", 403)
                    order = db.get(OrderRow, ticket.order_id)
                    if order is None or order.source_user_id != session.user_id:
                        raise BusinessError("order_not_found", 404)
                ticket.user_id = session.user_id
                db.add(ticket)
                db.flush()
                self._audit(
                    db,
                    ticket,
                    "ticket_created",
                    actor,
                    {"category": category, "reason_code": reason_code},
                    created_at=now,
                )
                self._audit(
                    db,
                    ticket,
                    "handoff_started",
                    actor,
                    {"status": "open"},
                    created_at=now,
                )
                created_result = self._ticket(ticket)
        except IntegrityError as exc:
            with Session(self.engine) as db:
                existing = db.scalar(
                    select(TicketRow).where(
                        TicketRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None or existing.session_id != session_id:
                    raise BusinessError("ticket_idempotency_key_conflict", 409) from exc
                result = self._ticket(existing)
                result["idempotent_replay"] = True
                return result
        created_result["idempotent_replay"] = False
        return created_result

    def list(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        assignee: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if status is not None and status not in TICKET_STATUSES:
            raise BusinessError("ticket_status_invalid", 422)
        if category is not None and category not in TICKET_CATEGORIES:
            raise BusinessError("ticket_category_invalid", 422)
        if offset < 0 or limit < 1 or limit > 100:
            raise BusinessError("ticket_pagination_invalid", 422)
        filters = []
        if status is not None:
            filters.append(TicketRow.status == status)
        if category is not None:
            filters.append(TicketRow.category == category)
        if assignee is not None:
            filters.append(TicketRow.assignee == assignee)
        if created_from is not None:
            filters.append(TicketRow.created_at >= created_from)
        if created_to is not None:
            filters.append(TicketRow.created_at <= created_to)
        with Session(self.engine) as db:
            total = db.scalar(select(func.count()).select_from(TicketRow).where(*filters))
            rows = db.scalars(
                select(TicketRow)
                .where(*filters)
                .order_by(TicketRow.created_at.desc(), TicketRow.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [self._ticket(row) for row in rows],
                "total": total or 0,
                "offset": offset,
                "limit": limit,
            }

    def detail(self, ticket_id: str) -> dict[str, Any]:
        with Session(self.engine) as db:
            ticket = self._get_ticket(db, ticket_id)
            session = db.get(SessionRow, ticket.session_id)
            request = (
                db.get(ExecutionRequestRow, ticket.request_id)
                if ticket.request_id and ticket.user_id is not None
                else None
            )
            messages = db.scalars(
                select(MessageRow)
                .where(MessageRow.session_id == ticket.session_id)
                .order_by(MessageRow.sequence.desc())
                .limit(20)
            ).all()
            audit_rows = db.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.ticket_id == ticket.id)
                .order_by(AuditEventRow.created_at, AuditEventRow.id)
            ).all()
            result = self._ticket(ticket)
            result["session"] = {
                "session_id": ticket.session_id,
                "identity_verified": bool(session and session.user_id),
            }
            result["request"] = (
                {
                    "request_id": request.id,
                    "action": request.action,
                    "order_id": request.order_id,
                    "status": request.status,
                    "proposal_id": request.proposal_id,
                    "proposed_parameters": sanitize_ticket_payload(request.arguments),
                    "confirmation_expires_at": request.confirmation_expires_at,
                    "failure_reason": request.failure_reason,
                }
                if request is not None
                else None
            )
            result["conversation"] = [
                {
                    "role": row.role,
                    "content": redact_checkpoint_content(row.content),
                    "sequence": row.sequence,
                    "created_at": row.created_at,
                }
                for row in reversed(messages)
            ]
            counts: dict[str, int] = {}
            for event in audit_rows:
                counts[event.event_type] = counts.get(event.event_type, 0) + 1
            result["audit_summary"] = {
                "event_count": len(audit_rows),
                "event_types": counts,
                "last_event_at": audit_rows[-1].created_at if audit_rows else None,
            }
            return result

    def assign(self, ticket_id: str, assignee: str, operator_id: str) -> dict[str, Any]:
        if not assignee.strip() or len(assignee) > 128:
            raise BusinessError("ticket_assignee_invalid", 422)
        now = int(self.clock())
        with Session(self.engine) as db, db.begin():
            ticket = self._get_ticket(db, ticket_id, lock=True)
            if ticket.status in {"closed", "cancelled"}:
                raise BusinessError("ticket_terminal", 409)
            previous = ticket.assignee
            ticket.assignee = assignee.strip()
            if ticket.status == "open":
                ticket.status = "assigned"
            ticket.updated_at = now
            self._audit(
                db,
                ticket,
                "ticket_assigned",
                "operator",
                {
                    "previous_assignee": previous,
                    "assignee": ticket.assignee,
                    "operator_id": operator_id,
                },
                created_at=now,
            )
            return self._ticket(ticket)

    def change_status(
        self,
        ticket_id: str,
        status: str,
        operator_id: str,
        *,
        close_reason: str | None = None,
    ) -> dict[str, Any]:
        if status not in TICKET_STATUSES:
            raise BusinessError("ticket_status_invalid", 422)
        now = int(self.clock())
        with Session(self.engine) as db, db.begin():
            ticket = self._get_ticket(db, ticket_id, lock=True)
            if status == ticket.status:
                return self._ticket(ticket)
            if status not in STATUS_TRANSITIONS[ticket.status]:
                raise BusinessError("ticket_status_transition_invalid", 409)
            if status in {"closed", "cancelled"}:
                if close_reason not in CLOSE_REASONS:
                    raise BusinessError("ticket_close_reason_required", 422)
            elif close_reason is not None:
                raise BusinessError("ticket_close_reason_not_allowed", 422)
            previous = ticket.status
            ticket.status = status
            ticket.updated_at = now
            ticket.closed_at = now if status in {"closed", "cancelled"} else None
            ticket.close_reason = close_reason
            self._audit(
                db,
                ticket,
                "ticket_status_changed",
                "operator",
                {
                    "from": previous,
                    "to": status,
                    "close_reason": close_reason,
                    "operator_id": operator_id,
                },
                created_at=now,
            )
            if status in {"resolved", "closed"}:
                self._audit(
                    db,
                    ticket,
                    "handoff_returned",
                    "operator",
                    {"status": status, "operator_id": operator_id},
                    created_at=now,
                )
            return self._ticket(ticket)

    def request_approval(
        self,
        ticket_id: str,
        *,
        request_id: str | None,
        action: str,
        proposed_params: dict[str, Any],
        operator_id: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        if not action.strip() or len(action) > 128:
            raise BusinessError("approval_action_invalid", 422)
        if ttl_seconds < 1 or ttl_seconds > 604_800:
            raise BusinessError("approval_ttl_invalid", 422)
        now = int(self.clock())
        safe_params = sanitize_ticket_payload(proposed_params)
        try:
            with Session(self.engine) as db, db.begin():
                ticket = self._get_ticket(db, ticket_id, lock=True)
                bound_request_id = request_id or ticket.request_id
                request = (
                    db.get(ExecutionRequestRow, bound_request_id)
                    if bound_request_id
                    else None
                )
                if bound_request_id and (
                    request is None
                    or request.session_id != ticket.session_id
                    or request.user_id != ticket.user_id
                ):
                    raise BusinessError("approval_request_binding_invalid", 409)
                existing = db.scalar(
                    select(ApprovalRow).where(
                        ApprovalRow.ticket_id == ticket.id,
                        ApprovalRow.request_id == bound_request_id,
                        ApprovalRow.action == action,
                    )
                )
                if existing is not None:
                    return self._approval(existing)
                approval = ApprovalRow(
                    id=uuid4().hex,
                    ticket_id=ticket.id,
                    request_id=bound_request_id,
                    action=action,
                    proposed_params=safe_params,
                    status="pending",
                    operator_id=None,
                    decision_reason=None,
                    created_at=now,
                    decided_at=None,
                    expires_at=now + ttl_seconds,
                )
                db.add(approval)
                db.flush()
                self._audit(
                    db,
                    ticket,
                    "approval_requested",
                    "operator",
                    {
                        "approval_id": approval.id,
                        "action": action,
                        "requested_by": operator_id,
                    },
                    created_at=now,
                )
                return self._approval(approval)
        except IntegrityError as exc:
            with Session(self.engine) as db:
                existing = db.scalar(
                    select(ApprovalRow).where(
                        ApprovalRow.ticket_id == ticket_id,
                        ApprovalRow.request_id == request_id,
                        ApprovalRow.action == action,
                    )
                )
                if existing is None:
                    raise BusinessError("approval_conflict", 409) from exc
                return self._approval(existing)

    def decide_approval(
        self,
        ticket_id: str,
        approval_id: str,
        *,
        decision: Literal["approved", "rejected"],
        reason: str,
        operator_id: str,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise BusinessError("approval_decision_reason_required", 422)
        now = int(self.clock())
        with Session(self.engine) as db, db.begin():
            ticket = self._get_ticket(db, ticket_id, lock=True)
            approval = db.scalar(
                select(ApprovalRow)
                .where(
                    ApprovalRow.id == approval_id,
                    ApprovalRow.ticket_id == ticket.id,
                )
                .with_for_update()
            )
            if approval is None:
                raise BusinessError("approval_not_found", 404)
            if approval.status != "pending":
                raise BusinessError("approval_already_decided", 409)
            if now > approval.expires_at:
                approval.status = "expired"
                approval.decided_at = now
                approval.operator_id = operator_id
                approval.decision_reason = "approval_expired"
                self._audit(
                    db,
                    ticket,
                    "approval_decided",
                    "system",
                    {"approval_id": approval.id, "decision": "expired"},
                    created_at=now,
                )
                failure = BusinessError("approval_expired", 409)
            else:
                approval.status = decision
                approval.decided_at = now
                approval.operator_id = operator_id
                approval.decision_reason = reason.strip()[:1_000]
                self._audit(
                    db,
                    ticket,
                    "approval_decided",
                    "operator",
                    {
                        "approval_id": approval.id,
                        "decision": decision,
                        "operator_id": operator_id,
                    },
                    created_at=now,
                )
                failure = None
            result = self._approval(approval)
        if failure is not None:
            raise failure
        return result

    def audit(self, ticket_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as db:
            self._get_ticket(db, ticket_id)
            rows = db.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.ticket_id == ticket_id)
                .order_by(AuditEventRow.created_at, AuditEventRow.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "session_id": row.session_id,
                    "ticket_id": row.ticket_id,
                    "request_id": row.request_id,
                    "order_id": row.order_id,
                    "actor": row.actor,
                    "payload": row.payload,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def approved_execution_binding(
        self, ticket_id: str, operator_id: str
    ) -> tuple[str, str, str, str]:
        """Require operator approval but never manufacture customer confirmation."""
        now = int(self.clock())
        with Session(self.engine) as db:
            ticket = self._get_ticket(db, ticket_id)
            if ticket.request_id is None:
                raise BusinessError("ticket_execution_request_required", 409)
            request = db.get(ExecutionRequestRow, ticket.request_id)
            if request is None or request.session_id != ticket.session_id:
                raise BusinessError("approval_request_binding_invalid", 409)
            action = f"execute_{request.action}"
            approval = db.scalar(
                select(ApprovalRow).where(
                    ApprovalRow.ticket_id == ticket.id,
                    ApprovalRow.request_id == request.id,
                    ApprovalRow.action == action,
                    ApprovalRow.status == "approved",
                )
            )
            if approval is None or approval.expires_at < now:
                raise BusinessError("operator_approval_required", 409)
            if not operator_id:
                raise BusinessError("operator_identity_required", 403)
            return (
                ticket.session_id,
                request.id,
                request.action,
                request.idempotency_key,
            )
