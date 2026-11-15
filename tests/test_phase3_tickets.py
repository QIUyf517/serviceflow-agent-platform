"""Phase 3 ticket, approval, operator-boundary, and handoff tests."""

import os
from uuid import uuid4

import pytest
from app.database import Base, MessageRow, OrderRow, TicketRow, engine_for, seed
from app.main import app, get_execution_service, get_service, get_ticket_service
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import EligibilityResult, ResolutionProposal
from app.multi_agent.workflow import SessionStateStore
from app.retail import validate
from app.service import BusinessError, RetailService
from app.ticketing import TicketService
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

OPERATOR_TOKEN = "phase3-local-operator-token"


def verified(service: RetailService) -> str:
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    return sid


def cancel_models() -> tuple[ResolutionProposal, EligibilityResult]:
    return (
        ResolutionProposal(
            proposal_id="phase3-ticket-proposal",
            task_id="cancel_order-proposal",
            action_type="cancel",
            order_id="o",
            proposed_parameters={"reason": "ordered by mistake"},
            requires_user_confirmation=True,
            requires_human_review=False,
            eligibility_status="eligible",
            status="pending_confirmation",
            explanation="Eligible under the deterministic rule.",
            validated=True,
        ),
        EligibilityResult(
            status="eligible",
            validated=True,
            rule_code="cancel_pending_order",
            checked_order_status="pending",
            explanation="The order is pending.",
        ),
    )


def client_for(service, monkeypatch):
    import app.main as api

    monkeypatch.setenv("OPERATOR_DEMO_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setenv("OPERATOR_DEMO_ID", "operator-test")
    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    execution = ExecutionService(service.engine)
    tickets = TicketService(service.engine)
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_execution_service] = lambda: execution
    app.dependency_overrides[get_ticket_service] = lambda: tickets
    return TestClient(app), execution


def operator_headers() -> dict[str, str]:
    return {"x-operator-token": OPERATOR_TOKEN}


def test_ticket_state_machine_idempotency_redaction_and_audit(service):
    sid = verified(service)
    tickets = TicketService(service.engine, clock=lambda: 1_700_000_000)
    first = tickets.create(
        sid,
        category="customer_requested_human",
        severity="medium",
        priority=3,
        reason_code="customer_requested_human",
        summary="Contact me at test@example.invalid; card 4111 1111 1111 1111",
        requested_action={"email": "test@example.invalid", "action": "human_review"},
        idempotency_key="phase3-ticket-idempotent-key",
        actor="user",
        agent_state={"task_status": "unsupported"},
        customer_explicit=True,
    )
    repeated = tickets.create(
        sid,
        category="customer_requested_human",
        severity="medium",
        priority=3,
        reason_code="customer_requested_human",
        summary="Different text cannot create a second ticket.",
        requested_action={},
        idempotency_key="phase3-ticket-idempotent-key",
        actor="user",
        customer_explicit=True,
    )
    assert repeated["id"] == first["id"] and repeated["idempotent_replay"] is True
    assert "test@example.invalid" not in first["summary"]
    assert first["requested_action"]["email"] == "[REDACTED]"

    assigned = tickets.assign(first["id"], "operator-test", "operator-test")
    assert assigned["status"] == "assigned"
    with pytest.raises(BusinessError, match="ticket_status_transition_invalid"):
        tickets.change_status(first["id"], "closed", "operator-test", close_reason="duplicate")
    tickets.change_status(first["id"], "in_progress", "operator-test")
    tickets.change_status(first["id"], "resolved", "operator-test")
    with pytest.raises(BusinessError, match="ticket_close_reason_required"):
        tickets.change_status(first["id"], "closed", "operator-test")
    closed = tickets.change_status(
        first["id"],
        "closed",
        "operator-test",
        close_reason="resolved_by_operator",
    )
    assert closed["closed_at"] == 1_700_000_000
    assert closed["close_reason"] == "resolved_by_operator"
    event_types = [event["event_type"] for event in tickets.audit(first["id"])]
    assert event_types.count("ticket_created") == 1
    assert event_types.count("handoff_started") == 1
    assert "ticket_assigned" in event_types
    assert "handoff_returned" in event_types
    with Session(service.engine) as db:
        assert db.scalar(select(func.count()).select_from(TicketRow)) == 1


def test_operator_api_is_separate_and_customer_ticket_response_is_honest(service, monkeypatch):
    client, _ = client_for(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        created = client.post(
            "/api/v1/tickets",
            headers={
                "x-session-id": sid,
                "idempotency-key": "phase3-explicit-ticket-key",
            },
            json={"summary": "Please connect me to support."},
        )
        assert created.status_code == 200
        ticket = created.json()
        assert ticket["user_id"] is None
        assert "尚未处理完成" in ticket["message"]

        customer_only = client.get(
            "/api/v1/tickets",
            headers={"x-session-id": sid},
        )
        assert customer_only.status_code == 401
        listed = client.get("/api/v1/tickets", headers=operator_headers())
        assert listed.status_code == 200 and listed.json()["total"] == 1
        detail = client.get(f"/api/v1/tickets/{ticket['id']}", headers=operator_headers()).json()
        assert detail["session"]["identity_verified"] is False
        assert detail["request"] is None
    finally:
        app.dependency_overrides.clear()


def test_only_explicit_human_request_creates_an_idempotent_ticket(service, monkeypatch):
    client, _ = client_for(service, monkeypatch)
    try:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        handoff = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "Please transfer me to a human agent"},
        )
        assert handoff.status_code == 200
        body = handoff.json()
        assert body["task_status"] == "handoff_created"
        assert "尚未处理完成" in body["final_response"]
        repeat = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "Please transfer me to a human agent"},
        ).json()
        assert repeat["ticket"]["id"] == body["ticket"]["id"]

        other = client.post("/api/v1/sessions").json()["session_id"]
        unsupported = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": other},
            json={"message": "Sing a song"},
        )
        assert unsupported.status_code == 200
        assert unsupported.json()["ticket"] is None
        repeated = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": other},
            json={"message": "Sing a song again"},
        )
        assert repeated.json()["ticket"] is None
        assert "智能客服当前无法解决" in repeated.json()["final_response"]
        assert "如需人工客服" in repeated.json()["final_response"]
        with Session(service.engine) as db:
            tickets = db.scalars(select(TicketRow).where(TicketRow.session_id == other)).all()
        assert tickets == []
    finally:
        app.dependency_overrides.clear()


def test_customer_reply_service_binds_ticket_reopens_and_deduplicates(service):
    sid = verified(service)
    other = service.start()
    service.verify(other, email="v@example.invalid")
    tickets = TicketService(service.engine, clock=lambda: 1_700_000_100)
    ticket = tickets.create(
        sid,
        category="customer_requested_human",
        severity="medium",
        priority=3,
        reason_code="customer_requested_human",
        summary="请求人工回复",
        requested_action={},
        idempotency_key="phase45c-service-ticket-key",
        actor="user",
    )
    tickets.assign(ticket["id"], "operator-demo", "operator-test")
    tickets.change_status(ticket["id"], "in_progress", "operator-test")
    tickets.change_status(ticket["id"], "waiting_customer", "operator-test")

    first = tickets.customer_reply(
        sid,
        ticket["id"],
        "好的，请继续帮我处理。",
        "phase45c-service-customer-reply",
    )
    assert first["status"] == "in_progress"
    assert first["idempotent_replay"] is False

    replay = tickets.customer_reply(
        sid,
        ticket["id"],
        "好的，请继续帮我处理。",
        "phase45c-service-customer-reply",
    )
    assert replay["sequence"] == first["sequence"]
    assert replay["idempotent_replay"] is True
    with pytest.raises(BusinessError, match="ticket_message_idempotency_conflict"):
        tickets.customer_reply(
            sid,
            ticket["id"],
            "冲突内容",
            "phase45c-service-customer-reply",
        )
    with pytest.raises(BusinessError, match="ticket_not_found"):
        tickets.customer_reply(
            other,
            ticket["id"],
            "不应写入",
            "phase45c-service-other-reply",
        )

    detail = tickets.detail(ticket["id"])
    assert detail["status"] == "in_progress"
    assert any(
        message["role"] == "user" and message["content"] == "好的，请继续帮我处理。"
        for message in detail["conversation"]
    )
    customer_reply_events = [
        event
        for event in tickets.audit(ticket["id"])
        if event["event_type"] == "customer_replied"
    ]
    assert len(customer_reply_events) == 1


def test_human_ticket_supports_bound_bidirectional_replies_and_is_audited(
    service, monkeypatch
):
    client, _ = client_for(service, monkeypatch)
    try:
        sid = verified(service)
        other = service.start()
        service.verify(other, email="v@example.invalid")
        ticket = client.post(
            "/api/v1/tickets",
            headers={"x-session-id": sid, "Idempotency-Key": "phase45c-human-reply"},
            json={
                "category": "customer_requested_human",
                "severity": "medium",
                "priority": 3,
                "reason_code": "customer_requested_human",
                "summary": "请求人工回复",
                "requested_action": {},
            },
        ).json()
        ticket_id = ticket["id"]
        assert client.get("/api/v1/customer/tickets", headers={"x-session-id": other}).json() == []
        assert (
            client.get(
                f"/api/v1/customer/tickets/{ticket_id}/updates", headers={"x-session-id": other}
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/tickets/{ticket_id}/reply", json={"content": "我来帮您查看。"}
            ).status_code
            == 401
        )
        reply = client.post(
            f"/api/v1/tickets/{ticket_id}/reply",
            headers=operator_headers(),
            json={"content": "我来帮您查看。"},
        )
        assert reply.status_code == 200

        assigned = client.post(
            f"/api/v1/tickets/{ticket_id}/assign",
            headers=operator_headers(),
            json={"assignee": "operator-demo"},
        )
        assert assigned.status_code == 200
        for status in ("in_progress", "waiting_customer"):
            changed = client.post(
                f"/api/v1/tickets/{ticket_id}/status",
                headers=operator_headers(),
                json={"status": status},
            )
            assert changed.status_code == 200

        updates = client.get(
            f"/api/v1/customer/tickets/{ticket_id}/updates", headers={"x-session-id": sid}
        ).json()
        assert updates["messages"][0]["content"] == "我来帮您查看。"

        customer_headers = {
            "x-session-id": sid,
            "Idempotency-Key": "phase45c-customer-reply-0001",
        }
        customer_reply = client.post(
            f"/api/v1/customer/tickets/{ticket_id}/messages",
            headers=customer_headers,
            json={"content": "好的，请继续帮我处理。"},
        )
        assert customer_reply.status_code == 200
        assert customer_reply.json()["status"] == "in_progress"
        assert customer_reply.json()["idempotent_replay"] is False

        replay = client.post(
            f"/api/v1/customer/tickets/{ticket_id}/messages",
            headers=customer_headers,
            json={"content": "好的，请继续帮我处理。"},
        )
        assert replay.status_code == 200
        assert replay.json()["sequence"] == customer_reply.json()["sequence"]
        assert replay.json()["idempotent_replay"] is True
        assert (
            client.post(
                f"/api/v1/customer/tickets/{ticket_id}/messages",
                headers=customer_headers,
                json={"content": "同一个请求标识不能改成其他内容。"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/v1/customer/tickets/{ticket_id}/messages",
                headers={
                    "x-session-id": other,
                    "Idempotency-Key": "phase45c-other-customer-reply",
                },
                json={"content": "不应写入。"},
            ).status_code
            == 404
        )

        detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=operator_headers()).json()
        assert any(message["role"] == "operator" for message in detail["conversation"])
        assert any(
            message["role"] == "user" and message["content"] == "好的，请继续帮我处理。"
            for message in detail["conversation"]
        )
        assert detail["status"] == "in_progress"
        assert detail["order"] is None
        audit = client.get(f"/api/v1/tickets/{ticket_id}/audit", headers=operator_headers()).json()
        assert any(item["event_type"] == "operator_replied" for item in audit["events"])
        assert any(item["event_type"] == "customer_replied" for item in audit["events"])
        with Session(service.engine) as db:
            customer_messages = db.scalars(
                select(MessageRow).where(
                    MessageRow.ticket_id == ticket_id,
                    MessageRow.role == "user",
                )
            ).all()
            assistant_messages = db.scalars(
                select(MessageRow).where(
                    MessageRow.ticket_id == ticket_id,
                    MessageRow.role == "assistant",
                )
            ).all()
        assert len(customer_messages) == 1
        assert assistant_messages == []
    finally:
        app.dependency_overrides.clear()


def test_approval_cannot_replace_confirmation_and_operator_reuses_executor(service, monkeypatch):
    client, execution = client_for(service, monkeypatch)
    try:
        sid = verified(service)
        planned, eligibility = cancel_models()
        request = execution.prepare_cancel(
            sid,
            planned,
            eligibility,
            "phase3-operator-execute-key",
        )
        created = client.post(
            "/api/v1/tickets",
            headers={
                "x-session-id": sid,
                "idempotency-key": "phase3-execution-ticket-key",
            },
            json={
                "summary": "Please transfer this pending request to an operator.",
                "order_id": "o",
                "request_id": request.request_id,
            },
        ).json()
        ticket_id = created["id"]
        approval = client.post(
            f"/api/v1/tickets/{ticket_id}/approvals",
            headers=operator_headers(),
            json={
                "request_id": request.request_id,
                "action": "execute_cancel",
                "proposed_params": {"reason": "ordered by mistake"},
            },
        )
        assert approval.status_code == 200
        decided = client.post(
            f"/api/v1/tickets/{ticket_id}/approvals/{approval.json()['id']}/decision",
            headers=operator_headers(),
            json={"decision": "approved", "reason": "Reviewed for demo execution."},
        )
        assert decided.status_code == 200

        premature = client.post(f"/api/v1/tickets/{ticket_id}/execute", headers=operator_headers())
        assert premature.status_code == 409
        assert premature.json()["error"]["code"] == "confirmation_required"
        assert service.order(sid, "o")["status"] == "pending"

        execution.record_decision(
            sid,
            request.request_id,
            decision="confirm",
            confirmation_text=request.confirmation_text,
        )
        result = client.post(f"/api/v1/tickets/{ticket_id}/execute", headers=operator_headers())
        assert result.status_code == 200
        assert result.json()["after_status"] == "cancelled"
        replay = client.post(
            f"/api/v1/tickets/{ticket_id}/execute", headers=operator_headers()
        ).json()
        assert replay["idempotent_replay"] is True
        with Session(service.engine) as db:
            assert db.get(OrderRow, "o").row_version == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.postgres
def test_postgres_ticket_approval_lifecycle_uses_disposable_schema(sample):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required for the phase 3 PostgreSQL acceptance test")
    engine = engine_for(url)
    schema = "phase3_tickets_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase3-tickets")
        service = RetailService(isolated)
        sid = verified(service)
        tickets = TicketService(isolated, clock=lambda: 1_700_000_000)
        ticket = tickets.create(
            sid,
            category="high_risk",
            severity="high",
            priority=1,
            reason_code="policy_evidence_insufficient_for_write",
            summary="Authoritative evidence is insufficient for a write request.",
            requested_action={"action": "human_review"},
            idempotency_key="phase3-postgres-ticket-key",
            actor="agent",
        )
        tickets.assign(ticket["id"], "operator-pg", "operator-pg")
        approval = tickets.request_approval(
            ticket["id"],
            request_id=None,
            action="recommendation",
            proposed_params={"note": "No business write is authorized."},
            operator_id="operator-pg",
            ttl_seconds=60,
        )
        decision = tickets.decide_approval(
            ticket["id"],
            approval["id"],
            decision="rejected",
            reason="Insufficient evidence.",
            operator_id="operator-pg",
        )
        assert decision["status"] == "rejected"
        assert [event["event_type"] for event in tickets.audit(ticket["id"])].count(
            "approval_decided"
        ) == 1
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
