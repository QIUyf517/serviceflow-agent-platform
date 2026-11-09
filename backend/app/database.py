"""Demo import tables; no evaluation tasks or policy authorization logic here."""

from typing import Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
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


class ConversationRow(Base):
    __tablename__ = "agent_conversations"
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"), primary_key=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(payload_type)
    pending_proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)


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
                ExecutionAuditRow,
                ConfirmationRecordRow,
                ExecutionRequestRow,
                AuditRow,
                ChatTraceRow,
                ConversationRow,
                ProposalRow,
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
