"""Demo import tables; no evaluation tasks or policy authorization logic here."""

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.retail import DataError, Retail


class Base(DeclarativeBase):
    pass


payload_type = JSON().with_variant(JSONB(), "postgresql")


class UserRow(Base):
    __tablename__ = "users"
    source_user_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_json: Mapped[dict[str, Any]] = mapped_column(payload_type)


class ProductRow(Base):
    __tablename__ = "products"
    source_product_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    product_json: Mapped[dict[str, Any]] = mapped_column(payload_type)


class OrderRow(Base):
    __tablename__ = "orders"
    source_order_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_user_id: Mapped[str] = mapped_column(ForeignKey("users.source_user_id"), index=True)
    status: Mapped[str] = mapped_column(String)
    order_json: Mapped[dict[str, Any]] = mapped_column(payload_type)
    row_version: Mapped[int] = mapped_column(default=1)


class OrderCreationRow(Base):
    """Identity-bound checkout command and immutable idempotency result."""

    __tablename__ = "order_creations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.source_user_id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.source_order_id"), unique=True)
    parameters_digest: Mapped[str] = mapped_column(String)
    request_json: Mapped[dict[str, Any]] = mapped_column(payload_type)
    result_json: Mapped[dict[str, Any]] = mapped_column(payload_type)
    created_at: Mapped[int] = mapped_column(Integer)


class ImportState(Base):
    __tablename__ = "import_state"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_hash: Mapped[str] = mapped_column(String)


class SessionRow(Base):
    __tablename__ = "service_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.source_user_id"), nullable=True)


class ProposalRow(Base):
    __tablename__ = "operation_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.source_order_id"))
    action: Mapped[str] = mapped_column(String)
    arguments: Mapped[dict[str, Any]] = mapped_column(payload_type)
    order_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    result: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)


class AuditRow(Base):
    __tablename__ = "operation_audit"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("operation_proposals.id"), unique=True)
    session_id: Mapped[str] = mapped_column(String)
    order_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    result: Mapped[dict[str, Any]] = mapped_column(payload_type)


class ExecutionRequestRow(Base):
    """Durable, identity-bound request for the controlled multi-agent executor."""

    __tablename__ = "execution_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.source_user_id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.source_order_id"), index=True)
    action: Mapped[str] = mapped_column(String)
    arguments: Mapped[dict[str, Any]] = mapped_column(payload_type)
    parameters_digest: Mapped[str] = mapped_column(String)
    proposal_id: Mapped[str] = mapped_column(String, index=True)
    proposal_version: Mapped[int] = mapped_column(Integer)
    proposal_digest: Mapped[str] = mapped_column(String)
    proposal_payload: Mapped[dict[str, Any]] = mapped_column(payload_type)
    task_id: Mapped[str] = mapped_column(String)
    eligibility: Mapped[dict[str, Any]] = mapped_column(payload_type)
    order_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, index=True)
    confirmation_expires_at: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attempt_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConfirmationRecordRow(Base):
    """A server-created decision bound to exactly one request/proposal version."""

    __tablename__ = "confirmation_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("execution_requests.id"), unique=True, index=True
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.source_user_id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.source_order_id"))
    action: Mapped[str] = mapped_column(String)
    proposal_id: Mapped[str] = mapped_column(String)
    proposal_version: Mapped[int] = mapped_column(Integer)
    proposal_digest: Mapped[str] = mapped_column(String)
    challenge_digest: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)


class ExecutionAuditRow(Base):
    """Append-only phase 2.5B lifecycle event without customer profile data."""

    __tablename__ = "execution_audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    eligibility: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)
    confirmation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    before_status: Mapped[str | None] = mapped_column(String, nullable=True)
    after_status: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ChatTraceRow(Base):
    __tablename__ = "chat_traces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"))
    events: Mapped[list[dict[str, Any]]] = mapped_column(payload_type)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)


class PolicyDocumentRow(Base):
    """One immutable upstream policy version; the raw source remains read-only."""

    __tablename__ = "policy_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_path: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)


class PolicyChunkRow(Base):
    """Section-aware policy text used by keyword and optional vector retrieval."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_policy_chunk_document_ordinal"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String)
    heading_path: Mapped[list[str]] = mapped_column(payload_type)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String)


class MerchantKnowledgeDocumentRow(Base):
    """Merchant-owned source whose published revision is copied into the RAG index."""

    __tablename__ = "merchant_knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_merchant_knowledge_status",
        ),
        UniqueConstraint("merchant_id", "content_sha256", name="uq_merchant_knowledge_content"),
        Index("ix_merchant_knowledge_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, index=True)
    source_label: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String)
    policy_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MerchantKnowledgeAuditRow(Base):
    """Append-only audit trail for merchant knowledge lifecycle writes."""

    __tablename__ = "merchant_knowledge_audit"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('draft_created', 'draft_updated', 'published', 'archived')",
            name="ck_merchant_knowledge_audit_event",
        ),
        Index("ix_merchant_knowledge_audit_document", "document_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(payload_type)
    created_at: Mapped[int] = mapped_column(Integer)


class ConversationRow(Base):
    __tablename__ = "agent_conversations"
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), primary_key=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(payload_type)
    pending_proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)


class SupportThreadRow(Base):
    """One server-owned conversation thread, optionally bound to a single order.

    The thread is the isolation boundary for messages, Agent checkpoints and human
    tickets. ``order_id`` is always derived from a server-side ownership check.
    """

    __tablename__ = "support_threads"
    __table_args__ = (
        CheckConstraint("kind IN ('order', 'general')", name="ck_support_threads_kind"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_support_threads_status"),
        CheckConstraint(
            "(kind = 'order' AND order_id IS NOT NULL) "
            "OR (kind = 'general' AND order_id IS NULL)",
            name="ck_support_threads_order_binding",
        ),
        Index(
            "uq_support_threads_session_order",
            "session_id",
            "order_id",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL"),
            sqlite_where=text("order_id IS NOT NULL"),
        ),
        Index(
            "uq_support_threads_session_general",
            "session_id",
            unique=True,
            postgresql_where=text("order_id IS NULL"),
            sqlite_where=text("order_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.source_user_id"), nullable=True, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.source_order_id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class TicketRow(Base):
    """Durable human-handoff ticket without customer profile fields."""

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "category IN ('unsupported_request', 'high_risk', 'rule_conflict', "
            "'execution_failed', 'clarification_exhausted', "
            "'customer_requested_human')",
            name="ck_tickets_category",
        ),
        CheckConstraint(
            "status IN ('open', 'assigned', 'in_progress', 'waiting_customer', "
            "'resolved', 'closed', 'cancelled')",
            name="ck_tickets_status",
        ),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('resolved_by_agent', "
            "'resolved_by_operator', 'customer_unresponsive', 'duplicate', "
            "'rejected', 'out_of_scope')",
            name="ck_tickets_close_reason",
        ),
        CheckConstraint(
            "status <> 'closed' OR (closed_at IS NOT NULL AND close_reason IS NOT NULL)",
            name="ck_tickets_closed_fields",
        ),
        Index("ix_tickets_status_created_at", "status", "created_at"),
        Index("ix_tickets_category_created_at", "category", "created_at"),
        Index("ix_tickets_assignee_created_at", "assignee", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String, unique=True, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), index=True)
    # Server-owned thread reference; no foreign key so legacy databases can be upgraded in place.
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.source_user_id"), nullable=True, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.source_order_id"), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_requests.id"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    requested_action: Mapped[dict[str, Any]] = mapped_column(payload_type)
    agent_state_digest: Mapped[str] = mapped_column(String)
    assignee: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    closed_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)


class MessageRow(Base):
    """Normalized conversation message retained alongside the phase-2 JSON record."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'operator')",
            name="ck_messages_role",
        ),
        CheckConstraint("sequence > 0", name="ck_messages_sequence_positive"),
        UniqueConstraint("session_id", "sequence", name="uq_messages_session_sequence"),
        Index("ix_messages_session_created_at", "session_id", "created_at"),
        Index("ix_messages_thread_sequence", "thread_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"))
    # Server-owned conversation thread; no foreign key so legacy databases can be upgraded.
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(payload_type)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)


class ApprovalRow(Base):
    """Operator decision record; it never substitutes for customer confirmation."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_approvals_status",
        ),
        UniqueConstraint(
            "ticket_id", "request_id", "action", name="uq_approvals_ticket_request_action"
        ),
        Index(
            "uq_approvals_ticket_action_without_request",
            "ticket_id",
            "action",
            unique=True,
            postgresql_where=text("request_id IS NULL"),
            sqlite_where=text("request_id IS NULL"),
        ),
        Index("ix_approvals_ticket_created_at", "ticket_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_requests.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String)
    proposed_params: Mapped[dict[str, Any]] = mapped_column(payload_type)
    status: Mapped[str] = mapped_column(String, index=True)
    operator_id: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    decided_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[int] = mapped_column(Integer)


class AuditEventRow(Base):
    """Unified append-only ticket, handoff, approval and recovery audit stream."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('ticket_created', 'ticket_assigned', "
            "'ticket_status_changed', 'approval_requested', 'approval_decided', "
            "'handoff_started', 'handoff_returned', 'recovery_attempted', "
            "'recovery_succeeded', 'recovery_failed', 'operator_replied', "
            "'customer_replied')",
            name="ck_audit_events_event_type",
        ),
        CheckConstraint(
            "actor IN ('user', 'agent', 'operator', 'system')",
            name="ck_audit_events_actor",
        ),
        Index("ix_audit_events_ticket_created_at", "ticket_id", "created_at"),
        Index("ix_audit_events_session_created_at", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), index=True)
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id"), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_requests.id"), nullable=True, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.source_order_id"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(payload_type)
    created_at: Mapped[int] = mapped_column(Integer)


def engine_for(url: str, *, testing: bool = False) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if not testing:
            raise DataError("SQLite is available only via explicit test mode")
        engine = create_engine(url, hide_parameters=True)

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: Any, _: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        return engine
    if parsed.get_backend_name() != "postgresql":
        raise DataError("PostgreSQL is required")
    if not parsed.database or not parsed.database.endswith("_demo"):
        raise DataError("Seed/reset requires a dedicated database name ending in _demo")
    return create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})


def ensure_execution_reliability_schema(engine: Engine) -> None:
    """Non-destructively add phase-3 lease columns to an existing phase-2 table."""
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(58326003)")
        existing = {
            column["name"]
            for column in inspect(connection).get_columns(
                ExecutionRequestRow.__tablename__, schema=schema
            )
        }
        quote = engine.dialect.identifier_preparer.quote
        table = quote(ExecutionRequestRow.__tablename__)
        if schema is not None:
            table = f"{quote(schema)}.{table}"
        additions = {
            "lease_owner": "VARCHAR",
            "lease_expires_at": "INTEGER",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "last_attempt_at": "INTEGER",
        }
        for column, ddl in additions.items():
            if column not in existing:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {quote(column)} {ddl}")


def seed(engine: Engine, db: Retail, source_hash: str, *, reset: bool = False) -> dict[str, int]:
    from sqlalchemy import delete, func, insert, select

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(58326001)")
        previous = conn.execute(select(ImportState.source_hash)).scalar_one_or_none()
        if previous != source_hash or reset:
            if previous and not reset:
                raise DataError("Different source snapshot; explicit --reset required")
            if not reset and any(
                conn.scalar(select(func.count()).select_from(table))
                for table in (UserRow, ProductRow, OrderRow)
            ):
                raise DataError("Unmanaged nonempty demo tables; explicit --reset required")
            for table in (
                AuditEventRow,
                ApprovalRow,
                MessageRow,
                TicketRow,
                ExecutionAuditRow,
                ConfirmationRecordRow,
                ExecutionRequestRow,
                AuditRow,
                ChatTraceRow,
                ConversationRow,
                ProposalRow,
                OrderCreationRow,
                SessionRow,
                OrderRow,
                ProductRow,
                UserRow,
                ImportState,
            ):
                conn.execute(delete(table))
            for model, rows in (
                (
                    UserRow,
                    [
                        {"source_user_id": u.user_id, "profile_json": u.model_dump()}
                        for u in db.users.values()
                    ],
                ),
                (
                    ProductRow,
                    [
                        {
                            "source_product_id": p.product_id,
                            "name": p.name,
                            "product_json": p.model_dump(),
                        }
                        for p in db.products.values()
                    ],
                ),
                (
                    OrderRow,
                    [
                        {
                            "source_order_id": o.order_id,
                            "source_user_id": o.user_id,
                            "status": o.status,
                            "order_json": o.model_dump(),
                            "row_version": 1,
                        }
                        for o in db.orders.values()
                    ],
                ),
            ):
                if rows:
                    conn.execute(insert(model), rows)
            conn.execute(insert(ImportState).values(id="retail", source_hash=source_hash))
        counts = {
            name: conn.scalar(select(func.count()).select_from(model))
            for name, model in (("users", UserRow), ("products", ProductRow), ("orders", OrderRow))
        }
        expected = {name: len(getattr(db, name)) for name in counts}
        if counts != expected:
            raise DataError("Database row counts differ from source; use explicit --reset")
    return counts
