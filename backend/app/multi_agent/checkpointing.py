"""LangGraph checkpoint backends bound to the existing business database URL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.engine import Engine

from app.config import Settings
from app.multi_agent.models import (
    ConfirmationRecord,
    EligibilityResult,
    ExecutionRequestSummary,
    ExecutionResult,
    ResolutionProposal,
    TaskPlan,
    TriageResult,
)

_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class CheckpointBackend:
    """Own a saver and its optional psycopg pool for one SQLAlchemy engine."""

    saver: BaseCheckpointSaver[Any]
    pool: ConnectionPool | None = None

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()


def checkpoint_key(engine: Engine) -> str:
    """Distinguish normal engines and schema-translated PostgreSQL test engines."""
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    return f"{engine.url.render_as_string(hide_password=True)}|schema={schema or ''}"


def _serializer() -> JsonPlusSerializer:
    """Use an explicit allowlist instead of permissive arbitrary object loading."""
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            TriageResult,
            TaskPlan,
            ResolutionProposal,
            EligibilityResult,
            ExecutionRequestSummary,
            ConfirmationRecord,
            ExecutionResult,
        )
    )


def build_checkpoint_backend(
    engine: Engine, settings: Settings | None = None
) -> CheckpointBackend:
    """Build the official PostgreSQL saver; SQLite remains an explicit test double."""
    if engine.dialect.name == "sqlite":
        return CheckpointBackend(InMemorySaver(serde=_serializer()))
    if engine.dialect.name != "postgresql":
        raise ValueError("checkpoint_postgresql_required")

    local = settings or Settings(_env_file=None)
    if (
        local.checkpoint_pool_min_size < 1
        or local.checkpoint_pool_max_size < local.checkpoint_pool_min_size
        or local.checkpoint_pool_timeout_seconds <= 0
    ):
        raise ValueError("checkpoint_pool_config_invalid")
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    if schema is not None and not _SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("checkpoint_schema_invalid")

    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    kwargs: dict[str, Any] = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }
    if schema is not None:
        kwargs["options"] = f"-csearch_path={schema}"
    pool = ConnectionPool(
        dsn,
        min_size=local.checkpoint_pool_min_size,
        max_size=local.checkpoint_pool_max_size,
        timeout=local.checkpoint_pool_timeout_seconds,
        kwargs=kwargs,
        open=False,
    )
    try:
        pool.open(wait=True)
        saver = PostgresSaver(pool, serde=_serializer())
        saver.setup()
    except Exception:
        pool.close()
        raise
    return CheckpointBackend(saver=saver, pool=pool)
