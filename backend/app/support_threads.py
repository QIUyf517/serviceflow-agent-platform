"""Server-owned conversation threads that keep each customer order isolated."""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import time
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    MessageRow,
    OrderRow,
    SessionRow,
    SupportThreadRow,
    TicketRow,
)
from app.service import BusinessError

_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def _schema_cache_key(engine: Engine) -> str | None:
    url = engine.url.render_as_string(hide_password=True)
    if ":memory:" in url or url in {"sqlite://", "sqlite:///"}:
        return None
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    return f"{url}|schema={schema or ''}"


def _qualified(engine: Engine, table: str) -> str:
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    quote = engine.dialect.identifier_preparer.quote
    return f"{quote(schema)}.{quote(table)}" if schema else quote(table)


def ensure_support_thread_schema(engine: Engine) -> dict[str, int]:
    """Add thread columns and backfill legacy rows without guessing order ownership."""
    cache_key = _schema_cache_key(engine)
    if cache_key is not None:
        with _SCHEMA_LOCK:
            if cache_key in _SCHEMA_READY:
                return {}
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(58326005)")
        inspector = inspect(connection)
        quote = engine.dialect.identifier_preparer.quote
        existing_tables = set(inspector.get_table_names(schema=schema))
        for table, index_name in (
            ("messages", "ix_messages_thread_id"),
            ("tickets", "ix_tickets_thread_id"),
        ):
            if table not in existing_tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
            if "thread_id" not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE {_qualified(engine, table)} "
                    f"ADD COLUMN {quote('thread_id')} VARCHAR"
                )
            indexes = {
                index["name"] for index in inspector.get_indexes(table, schema=schema)
            }
            if index_name not in indexes:
                connection.exec_driver_sql(
                    f"CREATE INDEX IF NOT EXISTS {quote(index_name)} "
                    f"ON {_qualified(engine, table)} ({quote('thread_id')})"
                )
        message_indexes = (
            {index["name"] for index in inspector.get_indexes("messages", schema=schema)}
            if "messages" in existing_tables
            else set()
        )
        if "ix_messages_thread_sequence" not in message_indexes and "messages" in existing_tables:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS "
                f"{quote('ix_messages_thread_sequence')} ON "
                f"{_qualified(engine, 'messages')} ({quote('thread_id')}, {quote('sequence')})"
            )
    counts = _backfill_threads(engine)
    if cache_key is not None:
        with _SCHEMA_LOCK:
            _SCHEMA_READY.add(cache_key)
    return counts


def _backfill_threads(engine: Engine) -> dict[str, int]:
    """Bind legacy tickets and messages; never infer an order from message text."""
    now = int(time())
    counts = {
        "order_threads_created": 0,
        "general_threads_created": 0,
        "tickets_bound": 0,
        "tickets_with_order_conflict": 0,
        "messages_bound_to_ticket": 0,
        "messages_bound_to_general": 0,
    }
    with Session(engine) as db, db.begin():
        pending_tickets = db.scalars(
            select(TicketRow).where(TicketRow.thread_id.is_(None))
        ).all()
        pending_messages = db.scalars(
            select(MessageRow).where(MessageRow.thread_id.is_(None))
        ).all()
        if not pending_tickets and not pending_messages:
            return counts
        existing_threads = {
            (thread.session_id, thread.order_id)
            for thread in db.scalars(select(SupportThreadRow)).all()
        }
        for ticket in pending_tickets:
            if ticket.order_id is not None:
                order = db.get(OrderRow, ticket.order_id)
                if order is None or (
                    ticket.user_id is not None and order.source_user_id != ticket.user_id
                ):
                    counts["tickets_with_order_conflict"] += 1
            thread = get_or_create_thread(
                db,
                session_id=ticket.session_id,
                user_id=ticket.user_id,
                order_id=ticket.order_id,
                now=now,
            )
            ticket.thread_id = thread.id
            counts["tickets_bound"] += 1
        db.flush()
        bound = {
            ticket.id: ticket.thread_id
            for ticket in db.scalars(
                select(TicketRow).where(TicketRow.thread_id.is_not(None))
            ).all()
        }
        general_threads: dict[str, str] = {}
        for message in pending_messages:
            thread_id = bound.get(message.ticket_id or "")
            if thread_id is None:
                thread_id = general_threads.get(message.session_id)
                if thread_id is None:
                    thread = get_or_create_thread(
                        db,
                        session_id=message.session_id,
                        user_id=None,
                        order_id=None,
                        now=now,
                    )
                    thread_id = thread.id
                    general_threads[message.session_id] = thread_id
                counts["messages_bound_to_general"] += 1
            else:
                counts["messages_bound_to_ticket"] += 1
            message.thread_id = thread_id
        created = {
            (thread.session_id, thread.order_id)
            for thread in db.scalars(select(SupportThreadRow)).all()
        } - existing_threads
        for _session_id, order_id in created:
            if order_id is None:
                counts["general_threads_created"] += 1
            else:
                counts["order_threads_created"] += 1
    return counts


def get_or_create_thread(
    db: Session,
    *,
    session_id: str,
    user_id: str | None,
    order_id: str | None,
    now: int,
) -> SupportThreadRow:
    statement = select(SupportThreadRow).where(SupportThreadRow.session_id == session_id)
    statement = (
        statement.where(SupportThreadRow.order_id == order_id)
        if order_id is not None
        else statement.where(SupportThreadRow.order_id.is_(None))
    )
    existing = db.scalar(statement)
    if existing is not None:
        if existing.user_id is None and user_id is not None:
            existing.user_id = user_id
        return existing
    thread = SupportThreadRow(
        id=uuid4().hex,
        session_id=session_id,
        user_id=user_id,
        order_id=order_id,
        kind="order" if order_id is not None else "general",
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(thread)
    db.flush()
    return thread


class SupportThreadService:
    """Resolve a conversation thread only from a server-verified session and order."""

    def __init__(self, engine: Engine, *, clock: Callable[[], float] = time) -> None:
        self.engine = engine
        self.clock = clock

    @staticmethod
    def projection(thread: SupportThreadRow) -> dict[str, Any]:
        return {
            "thread_id": thread.id,
            "kind": thread.kind,
            "order_id": thread.order_id,
            "status": thread.status,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
        }

    def resolve(self, session_id: str, order_id: str | None = None) -> dict[str, Any]:
        """Create or restore the thread for one verified session/order pair."""
        normalized_order = order_id.strip() if isinstance(order_id, str) else None
        if normalized_order == "":
            normalized_order = None
        now = int(self.clock())
        try:
            with Session(self.engine) as db, db.begin():
                session = db.scalar(
                    select(SessionRow).where(SessionRow.id == session_id).with_for_update()
                )
                if session is None:
                    raise BusinessError("session_not_found", 404)
                if normalized_order is not None:
                    if session.user_id is None:
                        raise BusinessError("identity_required", 403)
                    order = db.get(OrderRow, normalized_order)
                    if order is None or order.source_user_id != session.user_id:
                        raise BusinessError("order_not_found", 404)
                thread = get_or_create_thread(
                    db,
                    session_id=session_id,
                    user_id=session.user_id,
                    order_id=normalized_order,
                    now=now,
                )
                return self.projection(thread)
        except IntegrityError:
            with Session(self.engine) as db:
                statement = select(SupportThreadRow).where(
                    SupportThreadRow.session_id == session_id
                )
                statement = (
                    statement.where(SupportThreadRow.order_id == normalized_order)
                    if normalized_order is not None
                    else statement.where(SupportThreadRow.order_id.is_(None))
                )
                thread = db.scalar(statement)
                if thread is None:
                    raise BusinessError("thread_conflict", 409) from None
                return self.projection(thread)
