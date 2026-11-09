"""Phase 3.1 ticketing schema tests for SQLite and real PostgreSQL."""

import os
from uuid import uuid4

import pytest
from app.database import (
    ApprovalRow,
    AuditEventRow,
    Base,
    ConversationRow,
    MessageRow,
    TicketRow,
    engine_for,
    seed,
)
from app.retail import validate
from app.service import RetailService
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable


def _ticket(sid: str, *, ticket_id: str = "ticket-1") -> TicketRow:
    return TicketRow(
        id=ticket_id,
        ticket_no="SF-20261109-000001",
        session_id=sid,
        user_id="u",
        order_id="o",
        request_id=None,
        category="customer_requested_human",
        severity="medium",
        priority=50,
        status="open",
        reason_code="customer_requested_human",
        summary="Customer requested operator assistance for an order action.",
        requested_action={"action": "cancel", "order_id": "o"},
        agent_state_digest="digest-1",
        assignee=None,
        created_at=1_762_646_400,
        updated_at=1_762_646_400,
        closed_at=None,
        close_reason=None,
        idempotency_key="ticket-idempotency-1",
    )


def _insert_phase3_rows(engine, sid: str) -> None:
    with Session(engine) as db, db.begin():
        db.add(_ticket(sid))
        db.flush()
        db.add(
            MessageRow(
                id="message-1",
                session_id=sid,
                ticket_id="ticket-1",
                role="user",
                content="Please transfer me to a human operator.",
                meta={"redacted": True},
                trace_id="trace-1",
                sequence=1,
                created_at=1_762_646_401,
            )
        )
        db.add(
            ApprovalRow(
                id="approval-1",
                ticket_id="ticket-1",
                request_id=None,
                action="operator_recommendation",
                proposed_params={"recommendation": "request_more_information"},
                status="pending",
                operator_id=None,
                decision_reason=None,
                created_at=1_762_646_402,
                decided_at=None,
                expires_at=1_762_650_000,
            )
        )
        db.add(
            AuditEventRow(
                id="audit-1",
                event_type="ticket_created",
                session_id=sid,
                ticket_id="ticket-1",
                request_id=None,
                order_id="o",
                actor="system",
                payload={"category": "customer_requested_human"},
                created_at=1_762_646_403,
            )
        )


def test_phase3_models_keep_legacy_table_and_use_json_variants() -> None:
    expected = {"tickets", "messages", "approvals", "audit_events"}
    assert expected.issubset(Base.metadata.tables)
    assert ConversationRow.__tablename__ == "agent_conversations"

    for model, column in (
        (TicketRow, "requested_action"),
        (MessageRow, "meta"),
        (ApprovalRow, "proposed_params"),
        (AuditEventRow, "payload"),
    ):
        pg_ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        sqlite_ddl = str(CreateTable(model.__table__).compile(dialect=sqlite.dialect()))
        assert f"{column} JSONB" in pg_ddl
        assert f"{column} JSON" in sqlite_ddl


def test_phase3_sqlite_constraints_and_reset(sample, tmp_path) -> None:
    engine = engine_for(
        f"sqlite:///{(tmp_path / 'phase3-model.db').as_posix()}", testing=True
    )
    source = validate(sample)
    seed(engine, source, "phase3-model")
    service = RetailService(engine)
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    _insert_phase3_rows(engine, sid)

    with Session(engine) as db:
        assert db.scalar(select(TicketRow.ticket_no)) == "SF-20261109-000001"
        assert db.scalar(select(MessageRow.meta)) == {"redacted": True}
        assert db.scalar(select(ApprovalRow.status)) == "pending"
        assert db.scalar(select(AuditEventRow.actor)) == "system"

    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(
                MessageRow(
                    id="message-duplicate",
                    session_id=sid,
                    ticket_id=None,
                    role="assistant",
                    content="Duplicate sequence.",
                    meta={},
                    trace_id=None,
                    sequence=1,
                    created_at=1_762_646_404,
                )
            )

    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(
                ApprovalRow(
                    id="approval-duplicate",
                    ticket_id="ticket-1",
                    request_id=None,
                    action="operator_recommendation",
                    proposed_params={},
                    status="pending",
                    operator_id=None,
                    decision_reason=None,
                    created_at=1_762_646_405,
                    decided_at=None,
                    expires_at=1_762_650_000,
                )
            )

    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            invalid = _ticket(sid, ticket_id="ticket-invalid")
            invalid.ticket_no = "SF-20261109-000002"
            invalid.idempotency_key = "ticket-idempotency-2"
            invalid.status = "not-a-status"
            db.add(invalid)

    assert seed(engine, source, "phase3-model", reset=True) == {
        "users": 1,
        "products": 1,
        "orders": 1,
    }
    with Session(engine) as db:
        assert db.scalar(select(TicketRow.id)) is None
        assert db.scalar(select(ConversationRow.session_id)) is None
    engine.dispose()


@pytest.mark.postgres
def test_phase3_models_real_postgres_jsonb_indexes_and_constraints(sample) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    engine = engine_for(url)
    schema = "phase3_model_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase3-model-postgres")
        service = RetailService(isolated)
        sid = service.start()
        service.verify(sid, email="test@example.invalid")
        _insert_phase3_rows(isolated, sid)

        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                ).scalars()
            )
            assert {"tickets", "messages", "approvals", "audit_events"}.issubset(tables)
            assert "agent_conversations" in tables
            jsonb_columns = set(
                connection.execute(
                    text(
                        "SELECT table_name || '.' || column_name "
                        "FROM information_schema.columns "
                        "WHERE table_schema = :schema AND udt_name = 'jsonb'"
                    ),
                    {"schema": schema},
                ).scalars()
            )
            assert {
                "tickets.requested_action",
                "messages.meta",
                "approvals.proposed_params",
                "audit_events.payload",
            }.issubset(jsonb_columns)
            indexes = set(
                connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema"),
                    {"schema": schema},
                ).scalars()
            )
            assert {
                "ix_messages_session_created_at",
                "ix_tickets_status_created_at",
                "uq_approvals_ticket_action_without_request",
                "ix_audit_events_ticket_created_at",
            }.issubset(indexes)

        with pytest.raises(IntegrityError):
            with Session(isolated) as db, db.begin():
                duplicate = _ticket(sid, ticket_id="ticket-duplicate")
                duplicate.ticket_no = "SF-20261109-000003"
                db.add(duplicate)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
