"""Demo import tables; no evaluation tasks or policy authorization logic here."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, create_engine, event
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


class ChatTraceRow(Base):
    __tablename__ = "chat_traces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("service_sessions.id"))
    events: Mapped[list[dict[str, Any]]] = mapped_column(payload_type)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(payload_type, nullable=True)


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
