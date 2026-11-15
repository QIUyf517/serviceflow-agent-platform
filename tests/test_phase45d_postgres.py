"""Phase 4.5D: legacy PostgreSQL upgrade binds threads without guessing orders."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from app.database import Base, MessageRow, SupportThreadRow, TicketRow, engine_for, seed
from app.retail import validate
from app.support_threads import ensure_support_thread_schema
from app.ticketing import TicketService
from sqlalchemy import select, text
from sqlalchemy.orm import Session

LEGACY_TICKET = "legacy-ticket-0001"
LEGACY_SESSION = "legacy-session-0001"


@pytest.mark.postgres
def test_legacy_postgres_rows_gain_threads_without_text_guessing(sample) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    sample["users"]["v"] = deepcopy(sample["users"]["u"])
    sample["users"]["v"].update(user_id="v", email="v@example.invalid", orders=[])
    engine = engine_for(url)
    schema = "phase45d_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase45d-test")
        with isolated.begin() as connection:
            connection.exec_driver_sql(
                f'DROP INDEX IF EXISTS "{schema}"."ix_messages_thread_sequence"'
            )
            connection.exec_driver_sql(
                f'DROP INDEX IF EXISTS "{schema}"."ix_messages_thread_id"'
            )
            connection.exec_driver_sql(
                f'DROP INDEX IF EXISTS "{schema}"."ix_tickets_thread_id"'
            )
            connection.exec_driver_sql(f'ALTER TABLE "{schema}".messages DROP COLUMN thread_id')
            connection.exec_driver_sql(f'ALTER TABLE "{schema}".tickets DROP COLUMN thread_id')
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".service_sessions (id, user_id) '
                    "VALUES (:sid, 'u')"
                ),
                {"sid": LEGACY_SESSION},
            )
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".tickets (id, ticket_no, session_id, user_id, '
                    "order_id, request_id, category, severity, priority, status, reason_code, "
                    "summary, requested_action, agent_state_digest, assignee, created_at, "
                    "updated_at, closed_at, close_reason, idempotency_key) VALUES "
                    "(:id, 'SF-LEGACY-0001', :sid, 'u', 'o', NULL, "
                    "'customer_requested_human', 'medium', 3, 'open', "
                    "'customer_requested_human', '历史工单', '{}'::jsonb, :digest, NULL, "
                    "1700000000, 1700000000, NULL, NULL, 'legacy-idempotency-0001')"
                ),
                {"id": LEGACY_TICKET, "sid": LEGACY_SESSION, "digest": "0" * 64},
            )
            for message_id, ticket_id, role, content, sequence in (
                ("legacy-message-user", LEGACY_TICKET, "user", "历史顾客消息", 1),
                ("legacy-message-agent", LEGACY_TICKET, "assistant", "历史机器人回复", 2),
                ("legacy-message-free", None, "user", "历史未绑定消息", 3),
            ):
                connection.execute(
                    text(
                        f'INSERT INTO "{schema}".messages (id, session_id, ticket_id, role, '
                        "content, meta, trace_id, sequence, created_at) VALUES "
                        "(:id, :sid, :ticket, :role, :content, '{}'::jsonb, NULL, :sequence, "
                        "1700000000)"
                    ),
                    {
                        "id": message_id,
                        "sid": LEGACY_SESSION,
                        "ticket": ticket_id,
                        "role": role,
                        "content": content,
                        "sequence": sequence,
                    },
                )

        counts = ensure_support_thread_schema(isolated)
        assert counts["tickets_bound"] == 1
        assert counts["order_threads_created"] == 1
        assert counts["general_threads_created"] == 1
        assert counts["tickets_with_order_conflict"] == 0
        assert counts["messages_bound_to_ticket"] == 2
        assert counts["messages_bound_to_general"] == 1

        with Session(isolated) as db:
            ticket = db.get(TicketRow, LEGACY_TICKET)
            assert ticket is not None and ticket.thread_id is not None
            order_thread = db.get(SupportThreadRow, ticket.thread_id)
            assert order_thread is not None
            assert order_thread.kind == "order" and order_thread.order_id == "o"
            messages = db.scalars(
                select(MessageRow).where(MessageRow.session_id == LEGACY_SESSION)
            ).all()
            assert all(message.thread_id for message in messages)
            bound = {message.id: message.thread_id for message in messages}
            assert bound["legacy-message-user"] == ticket.thread_id
            assert bound["legacy-message-agent"] == ticket.thread_id
            assert bound["legacy-message-free"] != ticket.thread_id
            general_thread = db.get(SupportThreadRow, bound["legacy-message-free"])
            assert general_thread is not None
            assert general_thread.kind == "general" and general_thread.order_id is None

        assert ensure_support_thread_schema(isolated) == {}

        detail = TicketService(isolated).detail(LEGACY_TICKET)
        contents = [message["content"] for message in detail["conversation"]]
        assert "历史顾客消息" in contents
        assert "历史未绑定消息" not in contents
        assert detail["thread"]["kind"] == "order"
        assert detail["thread"]["order_id"] == "o"
        assert detail["related_tickets"] == {
            "same_order": [],
            "other_orders": {"total": 0, "items": []},
        }
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
