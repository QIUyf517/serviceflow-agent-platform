"""Phase 3.2 normalized messages and PostgreSQL checkpoint recovery."""

import os
from uuid import uuid4

import pytest
from app.config import Settings
from app.database import Base, MessageRow, engine_for, seed
from app.multi_agent.conversation import current_task_progress, run_after_sales_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.message_store import MessageStore, redact_checkpoint_content
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_execution_turn, run_turn
from app.retail import validate
from app.service import RetailService
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def test_normalized_messages_sequence_and_checkpoint_redaction(service) -> None:
    sid = service.start()
    store = MessageStore(service.engine)
    store.append(
        sid,
        "user",
        "email=secret@example.com address=1 Private Road card_number=4111111111111111",
    )
    store.append(sid, "assistant", "No business change was made.", trace_id="trace-1")

    with Session(service.engine) as db:
        rows = db.scalars(
            select(MessageRow)
            .where(MessageRow.session_id == sid)
            .order_by(MessageRow.sequence)
        ).all()
        assert [row.sequence for row in rows] == [1, 2]
        assert [row.role for row in rows] == ["user", "assistant"]
        assert "secret@example.com" in rows[0].content

    projected = store.checkpoint_messages(sid)
    assert "secret@example.com" not in str(projected)
    assert "1 Private Road" not in str(projected)
    assert "4111111111111111" not in str(projected)
    assert "[REDACTED_EMAIL]" in projected[0].content
    assert "[REDACTED_ADDRESS]" in projected[0].content
    assert "[REDACTED_PAYMENT]" in projected[0].content
    assert redact_checkpoint_content("token sk-1234567890abcdef") == (
        "token [REDACTED_SECRET]"
    )


@pytest.mark.postgres
def test_postgres_checkpoint_recovers_clarification_plan_and_confirmation(sample) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    engine = engine_for(url)
    schema = "phase3_checkpoint_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    stores: list[SessionStateStore] = []
    try:
        seed(isolated, validate(sample), "phase3-checkpoint")
        service = RetailService(isolated)
        execution = ExecutionService(isolated)
        policy = build_policy_agent(
            isolated,
            Settings(
                _env_file=None,
                agent_provider="mock",
                policy_retrieval_strategy="keyword",
                policy_top_k=3,
                policy_embedding_api_key=None,
            ),
        )
        sid = service.start()
        service.verify(sid, email="test@example.invalid")

        first_store = SessionStateStore()
        stores.append(first_store)
        clarification = run_turn(
            service,
            sid,
            "查询订单状态",
            MockTriage(),
            first_store,
            policy_agent=policy,
        )
        assert clarification["task_status"] == "clarification"
        assert clarification["thread_id"] == sid
        assert clarification["task_plan"][0]["task_id"] == "order-lookup"
        first_store.close()

        second_store = SessionStateStore()
        stores.append(second_store)
        queried = run_turn(
            service,
            sid,
            "o",
            MockTriage(),
            second_store,
            policy_agent=policy,
        )
        assert queried["task_status"] == "queried"
        assert queried["triage"]["order_id"] == "o"
        assert queried["task_plan"][0]["status"] == "completed"

        waiting = run_after_sales_conversation(
            service,
            execution,
            sid,
            (
                "email=private.person@example.com; address=9 Hidden Street; "
                "card_number=4111111111111111; "
                "Please cancel order o because ordered by mistake"
            ),
            second_store,
            policy,
        )
        assert waiting["task_status"] == "pending_confirmation"
        request_id = waiting["request_id"]
        progress_store = SessionStateStore()
        stores.append(progress_store)
        progress = current_task_progress(
            service,
            execution,
            sid,
            progress_store,
        )
        assert progress["pending_confirmation"]["request_id"] == request_id
        assert progress["task_plan"]
        assert progress["policy_context"]

        confirm_text, _ = execution.confirmation_phrases(sid, request_id)
        execution.record_decision(
            sid,
            request_id,
            decision="confirm",
            confirmation_text=confirm_text,
        )
        key = execution.get_request(sid, request_id).idempotency_key
        second_store.close()

        third_store = SessionStateStore()
        stores.append(third_store)
        result = run_execution_turn(execution, sid, request_id, key, third_store)
        assert result["task_status"] == "executed"
        assert result["execution_result"]["after_status"] == "cancelled"
        assert service.order(sid, "o")["status"] == "cancelled"

        with engine.connect() as connection:
            thread_ids = set(
                connection.execute(
                    text(f'SELECT DISTINCT thread_id FROM "{schema}".checkpoints')
                ).scalars()
            )
            assert thread_ids == {sid}
            checkpoint_json = "".join(
                connection.execute(
                    text(f'SELECT checkpoint::text FROM "{schema}".checkpoints')
                ).scalars()
            ).encode()
            blobs = b"".join(
                row[0] or b""
                for row in connection.execute(
                    text(f'SELECT blob FROM "{schema}".checkpoint_blobs')
                )
            ) + b"".join(
                row[0]
                for row in connection.execute(
                    text(f'SELECT blob FROM "{schema}".checkpoint_writes')
                )
            )
            persisted = checkpoint_json + blobs
            assert b"private.person@example.com" not in persisted
            assert b"9 Hidden Street" not in persisted
            assert b"4111111111111111" not in persisted
    finally:
        for store in stores:
            store.close()
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
