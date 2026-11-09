"""Trusted cancel/return execution boundary, independent from any LLM."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from copy import deepcopy
from time import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    ConfirmationRecordRow,
    ExecutionAuditRow,
    ExecutionRequestRow,
    UserRow,
)
from app.multi_agent.models import (
    ConfirmationRecord,
    EligibilityResult,
    ExecutionRequestSummary,
    ExecutionResult,
    ResolutionProposal,
)
from app.service import Action, BusinessError, RetailService

Decision = Literal["confirm", "reject"]
ExecutableAction = Literal["cancel", "return"]


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class ExecutionService:
    """Persistent confirmation, idempotency, transaction and audit boundary."""

    def __init__(
        self,
        engine: Engine,
        *,
        confirmation_ttl_seconds: int = 900,
        clock: Callable[[], float] = time,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if confirmation_ttl_seconds < 1 or confirmation_ttl_seconds > 3600:
            raise ValueError("confirmation_ttl_invalid")
        self.engine = engine
        self.retail = RetailService(engine)
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.clock = clock
        self.fault_injector = fault_injector
        Base.metadata.create_all(engine)

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if not isinstance(value, str) or not 16 <= len(value) <= 128:
            raise BusinessError("idempotency_key_invalid")
        if any(character.isspace() for character in value):
            raise BusinessError("idempotency_key_invalid")
        return value

    @staticmethod
    def _proposal_payload(proposal: ResolutionProposal) -> dict[str, Any]:
        return proposal.model_dump(mode="json")

    @staticmethod
    def _confirmation_text(request: ExecutionRequestRow) -> str:
        if request.action == "cancel":
            detail = f"reason={request.arguments.get('reason', '')}"
        elif request.action == "return":
            quantities = json.dumps(
                request.arguments.get("item_quantities", {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            detail = (
                f"items={quantities} "
                f"refund_method={request.arguments.get('payment_method_id', '')}"
            )
        else:
            raise BusinessError("execution_action_not_allowed", 403)
        return (
            f"confirm {request.action}_order order={request.order_id} {detail} "
            f"proposal={request.proposal_id} version={request.proposal_version}"
        )

    @staticmethod
    def _rejection_text(request: ExecutionRequestRow) -> str:
        label = "取消" if request.action == "cancel" else "退货申请"
        return (
            f"拒绝{label} {request.order_id}，"
            f"方案：{request.proposal_id}，版本：{request.proposal_version}"
        )

    @staticmethod
    def _parameters_digest(
        *, user_id: str, order_id: str, action: str, arguments: dict[str, Any]
    ) -> str:
        return _digest(
            {
                "user_id": user_id,
                "order_id": order_id,
                "action": action,
                "arguments": arguments,
            }
        )

    @staticmethod
    def _binding_valid(request: ExecutionRequestRow) -> bool:
        return secrets.compare_digest(
            request.parameters_digest,
            ExecutionService._parameters_digest(
                user_id=request.user_id,
                order_id=request.order_id,
                action=request.action,
                arguments=request.arguments,
            ),
        ) and secrets.compare_digest(
            request.proposal_digest,
            _digest(request.proposal_payload),
        )

    @staticmethod
    def _audit(
        db: Session,
        request: ExecutionRequestRow,
        event_type: str,
        *,
        created_at: int,
        confirmation_id: str | None = None,
        before_status: str | None = None,
        after_status: str | None = None,
        result: dict[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> None:
        db.add(
            ExecutionAuditRow(
                id=uuid4().hex,
                request_id=request.id,
                task_id=request.task_id,
                session_id=request.session_id,
                user_id=request.user_id,
                order_id=request.order_id,
                action=request.action,
                proposal_id=request.proposal_id,
                eligibility=deepcopy(request.eligibility),
                confirmation_id=confirmation_id,
                event_type=event_type,
                before_status=before_status,
                after_status=after_status,
                result=deepcopy(result),
                failure_reason=failure_reason,
                created_at=created_at,
            )
        )

    def _summary(
        self, request: ExecutionRequestRow, *, include_confirmation_text: bool = False
    ) -> ExecutionRequestSummary:
        parameters = {
            key: value
            for key, value in request.arguments.items()
            if key not in {"kind", "order_id", "item_ids", "new_item_ids", "address"}
            and value not in (None, [], {})
        }
        if request.action == "cancel":
            summary = f"Cancel order {request.order_id}; reason={parameters.get('reason')}"
        elif request.action == "return":
            summary = (
                f"Register return request for order {request.order_id}; "
                f"items={parameters.get('item_quantities')}; "
                f"refund_method={parameters.get('payment_method_id')}; "
                "impact=order status becomes return requested; refund is not disbursed"
            )
        else:
            raise BusinessError("execution_action_not_allowed", 403)
        return ExecutionRequestSummary(
            request_id=request.id,
            idempotency_key=request.idempotency_key,
            task_id=request.task_id,
            proposal_id=request.proposal_id,
            proposal_version=request.proposal_version,
            proposal_digest=request.proposal_digest,
            order_id=request.order_id,
            action_type=request.action,
            proposed_parameters=parameters,
            summary=summary,
            status=request.status,
            confirmation_expires_at=request.confirmation_expires_at,
            confirmation_text=(
                self._confirmation_text(request) if include_confirmation_text else None
            ),
        )

    @staticmethod
    def _confirmation(record: ConfirmationRecordRow) -> ConfirmationRecord:
        return ConfirmationRecord(
            confirmation_id=record.id,
            request_id=record.request_id,
            proposal_id=record.proposal_id,
            proposal_version=record.proposal_version,
            proposal_digest=record.proposal_digest,
            order_id=record.order_id,
            action_type=record.action,
            decision=record.decision,
            status=record.status,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    def prepare_action(
        self,
        sid: str,
        proposal: ResolutionProposal,
        eligibility: EligibilityResult,
        idempotency_key: str,
    ) -> ExecutionRequestSummary:
        """Persist an eligible cancel/return request without changing the order."""
        key = self._validate_idempotency_key(idempotency_key)
        if (
            proposal.action_type not in {"cancel", "return"}
            or proposal.order_id is None
            or proposal.status != "pending_confirmation"
            or not proposal.validated
            or proposal.eligibility_status != "eligible"
            or not proposal.requires_user_confirmation
            or not eligibility.validated
            or eligibility.status != "eligible"
        ):
            raise BusinessError("proposal_not_executable")
        expected_parameters = {
            "cancel": {"reason"},
            "return": {"item_quantities", "payment_method_id"},
        }[proposal.action_type]
        if set(proposal.proposed_parameters) != expected_parameters:
            raise BusinessError("proposal_parameters_invalid")
        try:
            action = Action.model_validate(
                {
                    "kind": proposal.action_type,
                    "order_id": proposal.order_id,
                    **proposal.proposed_parameters,
                },
                strict=True,
            )
        except ValidationError as exc:
            raise BusinessError("proposal_parameters_invalid") from exc
        now = int(self.clock())
        payload = self._proposal_payload(proposal)
        proposal_digest = _digest(payload)
        eligibility_payload = eligibility.model_dump(mode="json")
        with Session(self.engine) as db, db.begin():
            session = self.retail._session(db, sid)
            existing = db.scalar(
                select(ExecutionRequestRow)
                .where(ExecutionRequestRow.idempotency_key == key)
                .with_for_update()
            )
            parameters_digest = self._parameters_digest(
                user_id=session.user_id,
                order_id=action.order_id,
                action=proposal.action_type,
                arguments=action.model_dump(mode="json"),
            )
            if existing is not None:
                if (
                    existing.session_id != sid
                    or existing.user_id != session.user_id
                    or not secrets.compare_digest(
                        existing.parameters_digest, parameters_digest
                    )
                    or not secrets.compare_digest(existing.proposal_digest, proposal_digest)
                ):
                    raise BusinessError("idempotency_key_conflict", 409)
                return self._summary(
                    existing,
                    include_confirmation_text=existing.status == "pending_confirmation",
                )
            order = self.retail._own_order(db, session.user_id, action.order_id, lock=True)
            user = db.get(UserRow, session.user_id)
            self.retail._apply(
                db,
                deepcopy(order.order_json),
                deepcopy(user.profile_json),
                action,
            )
            request = ExecutionRequestRow(
                id=uuid4().hex,
                idempotency_key=key,
                session_id=sid,
                user_id=session.user_id,
                order_id=action.order_id,
                action=proposal.action_type,
                arguments=action.model_dump(mode="json"),
                parameters_digest=parameters_digest,
                proposal_id=proposal.proposal_id,
                proposal_version=1,
                proposal_digest=proposal_digest,
                proposal_payload=payload,
                task_id=proposal.task_id,
                eligibility=eligibility_payload,
                order_version=order.row_version,
                status="pending_confirmation",
                confirmation_expires_at=now + self.confirmation_ttl_seconds,
                result=None,
                failure_reason=None,
                created_at=now,
                updated_at=now,
            )
            db.add(request)
            db.flush()
            self._audit(db, request, "proposal_generated", created_at=now)
            self._audit(db, request, "eligibility_validated", created_at=now)
            return self._summary(request, include_confirmation_text=True)

    def prepare_cancel(
        self,
        sid: str,
        proposal: ResolutionProposal,
        eligibility: EligibilityResult,
        idempotency_key: str,
    ) -> ExecutionRequestSummary:
        if proposal.action_type != "cancel":
            raise BusinessError("proposal_not_executable")
        return self.prepare_action(sid, proposal, eligibility, idempotency_key)

    def prepare_return(
        self,
        sid: str,
        proposal: ResolutionProposal,
        eligibility: EligibilityResult,
        idempotency_key: str,
    ) -> ExecutionRequestSummary:
        if proposal.action_type != "return":
            raise BusinessError("proposal_not_executable")
        return self.prepare_action(sid, proposal, eligibility, idempotency_key)

    def get_request(self, sid: str, request_id: str) -> ExecutionRequestSummary:
        with Session(self.engine) as db:
            session = self.retail._session(db, sid)
            request = db.get(ExecutionRequestRow, request_id)
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            return self._summary(
                request,
                include_confirmation_text=request.status == "pending_confirmation",
            )

    def confirmation_phrases(self, sid: str, request_id: str) -> tuple[str, str]:
        """Return operation-specific phrases after rechecking the authenticated owner."""
        with Session(self.engine) as db:
            session = self.retail._session(db, sid)
            request = db.get(ExecutionRequestRow, request_id)
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            return self._confirmation_text(request), self._rejection_text(request)

    def supersede_request(
        self, sid: str, request_id: str, *, reason: str = "superseded_by_new_request"
    ) -> ExecutionRequestSummary:
        """Invalidate an unexecuted request when the user changes the operation."""
        now = int(self.clock())
        with Session(self.engine) as db, db.begin():
            session = self.retail._session(db, sid)
            request = db.scalar(
                select(ExecutionRequestRow)
                .where(ExecutionRequestRow.id == request_id)
                .with_for_update()
            )
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            if request.status in {"succeeded", "rejected", "expired", "failed"}:
                return self._summary(request)
            if request.status != "superseded":
                request.status = "superseded"
                request.failure_reason = reason
                request.updated_at = now
                confirmation = db.scalar(
                    select(ConfirmationRecordRow).where(
                        ConfirmationRecordRow.request_id == request.id
                    )
                )
                if confirmation is not None and confirmation.status == "valid":
                    confirmation.status = "invalidated"
                self._audit(
                    db,
                    request,
                    "request_superseded",
                    created_at=now,
                    confirmation_id=confirmation.id if confirmation else None,
                    failure_reason=reason,
                )
            return self._summary(request)

    def execution_context(
        self, sid: str, request_id: str
    ) -> tuple[ExecutionRequestSummary, ResolutionProposal, EligibilityResult]:
        with Session(self.engine) as db:
            session = self.retail._session(db, sid)
            request = db.get(ExecutionRequestRow, request_id)
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            try:
                proposal = ResolutionProposal.model_validate(request.proposal_payload, strict=True)
                eligibility = EligibilityResult.model_validate(request.eligibility, strict=True)
            except ValidationError as exc:
                raise BusinessError("execution_request_corrupt", 409) from exc
            return self._summary(request), proposal, eligibility

    def record_decision(
        self,
        sid: str,
        request_id: str,
        *,
        decision: Decision,
        confirmation_text: str,
    ) -> ConfirmationRecord:
        if decision not in {"confirm", "reject"}:
            raise BusinessError("confirmation_decision_invalid")
        now = int(self.clock())
        failure: BusinessError | None = None
        created: ConfirmationRecord | None = None
        with Session(self.engine) as db, db.begin():
            session = self.retail._session(db, sid)
            request = db.scalar(
                select(ExecutionRequestRow)
                .where(ExecutionRequestRow.id == request_id)
                .with_for_update()
            )
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            existing = db.scalar(
                select(ConfirmationRecordRow).where(
                    ConfirmationRecordRow.request_id == request.id
                )
            )
            if existing is not None:
                if existing.decision == decision and self._binding_valid(request):
                    return self._confirmation(existing)
                raise BusinessError("confirmation_already_recorded", 409)
            if request.status != "pending_confirmation":
                raise BusinessError("confirmation_not_pending", 409)
            expected_text = self._confirmation_text(request)
            if not secrets.compare_digest(
                confirmation_text.encode("utf-8"), expected_text.encode("utf-8")
            ):
                self._audit(
                    db,
                    request,
                    "confirmation_failed",
                    created_at=now,
                    failure_reason="confirmation_text_mismatch",
                )
                failure = BusinessError("confirmation_text_mismatch")
            elif not self._binding_valid(request):
                self._audit(
                    db,
                    request,
                    "confirmation_failed",
                    created_at=now,
                    failure_reason="proposal_binding_invalid",
                )
                failure = BusinessError("proposal_binding_invalid", 409)
            elif now > request.confirmation_expires_at:
                request.status = "expired"
                request.updated_at = now
                request.failure_reason = "confirmation_expired"
                self._audit(
                    db,
                    request,
                    "confirmation_expired",
                    created_at=now,
                    failure_reason="confirmation_expired",
                )
                failure = BusinessError("confirmation_expired", 409)
            else:
                record = ConfirmationRecordRow(
                    id=uuid4().hex,
                    request_id=request.id,
                    session_id=sid,
                    user_id=session.user_id,
                    order_id=request.order_id,
                    action=request.action,
                    proposal_id=request.proposal_id,
                    proposal_version=request.proposal_version,
                    proposal_digest=request.proposal_digest,
                    challenge_digest=_digest(expected_text),
                    decision=decision,
                    status="valid" if decision == "confirm" else "rejected",
                    created_at=now,
                    expires_at=request.confirmation_expires_at,
                )
                db.add(record)
                request.status = "confirmed" if decision == "confirm" else "rejected"
                request.updated_at = now
                self._audit(
                    db,
                    request,
                    "user_confirmed" if decision == "confirm" else "user_rejected",
                    created_at=now,
                    confirmation_id=record.id,
                )
                db.flush()
                created = self._confirmation(record)
        if failure is not None:
            raise failure
        if created is None:
            raise BusinessError("confirmation_failed")
        return created

    def get_confirmation(self, sid: str, request_id: str) -> ConfirmationRecord:
        with Session(self.engine) as db:
            session = self.retail._session(db, sid)
            request = db.get(ExecutionRequestRow, request_id)
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            record = db.scalar(
                select(ConfirmationRecordRow).where(
                    ConfirmationRecordRow.request_id == request_id
                )
            )
            if record is None:
                raise BusinessError("confirmation_required", 409)
            return self._confirmation(record)

    def _record_execution_failure(self, sid: str, request_id: str, code: str) -> None:
        try:
            now = int(self.clock())
            with Session(self.engine) as db, db.begin():
                request = db.get(ExecutionRequestRow, request_id)
                if request is None or request.session_id != sid:
                    return
                request.status = "failed"
                request.failure_reason = code
                request.updated_at = now
                confirmation = db.scalar(
                    select(ConfirmationRecordRow).where(
                        ConfirmationRecordRow.request_id == request_id
                    )
                )
                if confirmation is not None and confirmation.status == "valid":
                    confirmation.status = "invalidated"
                self._audit(
                    db,
                    request,
                    "execution_failed",
                    created_at=now,
                    confirmation_id=confirmation.id if confirmation else None,
                    failure_reason=code,
                )
        except SQLAlchemyError:
            # The original database error remains authoritative; audit is best effort here.
            return

    def execute_action(
        self, sid: str, request_id: str, *, idempotency_key: str
    ) -> ExecutionResult:
        """Lock, revalidate and atomically execute one allowed request."""
        key = self._validate_idempotency_key(idempotency_key)
        try:
            with Session(self.engine) as db, db.begin():
                session = self.retail._session(db, sid)
                request = db.scalar(
                    select(ExecutionRequestRow)
                    .where(ExecutionRequestRow.id == request_id)
                    .with_for_update()
                )
                if (
                    request is None
                    or request.session_id != sid
                    or request.user_id != session.user_id
                ):
                    raise BusinessError("execution_request_not_found", 404)
                if not secrets.compare_digest(request.idempotency_key, key):
                    raise BusinessError("idempotency_key_conflict", 409)
                if request.status == "succeeded" and request.result is not None:
                    replay = deepcopy(request.result)
                    replay["idempotent_replay"] = True
                    return ExecutionResult.model_validate(replay, strict=True)
                if request.status != "confirmed":
                    code = {
                        "rejected": "confirmation_rejected",
                        "expired": "confirmation_expired",
                        "failed": request.failure_reason or "execution_request_failed",
                        "superseded": "execution_request_superseded",
                    }.get(request.status, "confirmation_required")
                    raise BusinessError(code, 409)
                if request.action not in {"cancel", "return"} or not self._binding_valid(request):
                    raise BusinessError("proposal_binding_invalid", 409)
                confirmation = db.scalar(
                    select(ConfirmationRecordRow)
                    .where(ConfirmationRecordRow.request_id == request.id)
                    .with_for_update()
                )
                if (
                    confirmation is None
                    or confirmation.status != "valid"
                    or confirmation.decision != "confirm"
                    or confirmation.session_id != sid
                    or confirmation.user_id != session.user_id
                    or confirmation.order_id != request.order_id
                    or confirmation.action != request.action
                    or confirmation.proposal_id != request.proposal_id
                    or confirmation.proposal_version != request.proposal_version
                    or not secrets.compare_digest(
                        confirmation.proposal_digest, request.proposal_digest
                    )
                ):
                    raise BusinessError("confirmation_binding_invalid", 409)
                now = int(self.clock())
                if now > confirmation.expires_at:
                    raise BusinessError("confirmation_expired", 409)
                order = self.retail._own_order(
                    db, session.user_id, request.order_id, lock=True
                )
                before_status = order.status
                if order.row_version != request.order_version:
                    raise BusinessError("order_changed", 409)
                user = db.get(UserRow, session.user_id)
                order_json = deepcopy(order.order_json)
                user_json = deepcopy(user.profile_json)
                action = Action.model_validate(request.arguments, strict=True)
                self.retail._apply(db, order_json, user_json, action)
                order.order_json = order_json
                order.status = order_json["status"]
                order.row_version += 1
                user.profile_json = user_json
                confirmation.status = "consumed"
                result = ExecutionResult(
                    request_id=request.id,
                    proposal_id=request.proposal_id,
                    confirmation_id=confirmation.id,
                    status="succeeded",
                    action_type=request.action,
                    order_id=order.source_order_id,
                    before_status=before_status,
                    after_status=order.status,
                    row_version=order.row_version,
                    idempotent_replay=False,
                )
                request.status = "succeeded"
                request.result = result.model_dump(mode="json")
                request.updated_at = now
                request.failure_reason = None
                if self.fault_injector is not None:
                    self.fault_injector("before_commit")
                self._audit(
                    db,
                    request,
                    "execution_succeeded",
                    created_at=now,
                    confirmation_id=confirmation.id,
                    before_status=before_status,
                    after_status=order.status,
                    result=result.model_dump(mode="json"),
                )
                return result
        except BusinessError as exc:
            if exc.code not in {
                "execution_request_not_found",
                "idempotency_key_conflict",
                "confirmation_required",
                "confirmation_rejected",
                "confirmation_expired",
            }:
                self._record_execution_failure(sid, request_id, exc.code)
            raise
        except (SQLAlchemyError, ValidationError) as exc:
            self._record_execution_failure(sid, request_id, "database_transaction_failed")
            raise BusinessError("database_transaction_failed", 503) from exc

    def execute_cancel(
        self, sid: str, request_id: str, *, idempotency_key: str
    ) -> ExecutionResult:
        request = self.get_request(sid, request_id)
        if request.action_type != "cancel":
            raise BusinessError("execution_action_mismatch", 409)
        return self.execute_action(sid, request_id, idempotency_key=idempotency_key)

    def execute_return(
        self, sid: str, request_id: str, *, idempotency_key: str
    ) -> ExecutionResult:
        request = self.get_request(sid, request_id)
        if request.action_type != "return":
            raise BusinessError("execution_action_mismatch", 409)
        return self.execute_action(sid, request_id, idempotency_key=idempotency_key)

    def audit_events(self, sid: str, request_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as db:
            session = self.retail._session(db, sid)
            request = db.get(ExecutionRequestRow, request_id)
            if (
                request is None
                or request.session_id != sid
                or request.user_id != session.user_id
            ):
                raise BusinessError("execution_request_not_found", 404)
            events = db.scalars(
                select(ExecutionAuditRow)
                .where(ExecutionAuditRow.request_id == request_id)
                .order_by(ExecutionAuditRow.created_at, ExecutionAuditRow.id)
            ).all()
            return [
                {
                    "event_id": event.id,
                    "request_id": event.request_id,
                    "task_id": event.task_id,
                    "user_id": event.user_id,
                    "order_id": event.order_id,
                    "action": event.action,
                    "proposal_id": event.proposal_id,
                    "eligibility": deepcopy(event.eligibility),
                    "confirmation_id": event.confirmation_id,
                    "event_type": event.event_type,
                    "before_status": event.before_status,
                    "after_status": event.after_status,
                    "result": deepcopy(event.result),
                    "failure_reason": event.failure_reason,
                    "created_at": event.created_at,
                }
                for event in events
            ]
