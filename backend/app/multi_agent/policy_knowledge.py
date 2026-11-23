"""Versioned policy loading plus keyword and optional pgvector retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import Engine, delete, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base, PolicyChunkRow, PolicyDocumentRow

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WORDS = re.compile(r"[a-z0-9]+", re.I)
CJK = re.compile(r"[\u3400-\u9fff]+")
SAFE_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PolicyKnowledgeError(Exception):
    """Safe policy index or retrieval error."""


class VectorUnavailableError(PolicyKnowledgeError):
    """The configured vector path cannot run; never replace its result silently."""


class PolicyChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    ordinal: int
    section: str
    heading_path: list[str]
    source: str
    version: str
    content: str
    content_sha256: str


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    title: str
    source: str
    version: str
    source_sha256: str
    chunks: list[PolicyChunk]


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    source_sha256: str
    chunks: int
    inserted: int
    unchanged: bool
    rebuilt: bool


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    section: str
    heading_path: list[str]
    source: str
    version: str
    content: str
    score: float
    retrieval_method: str


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    method: str
    top_k: int
    elapsed_ms: float
    terms: list[str]
    hits: list[SearchHit]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_policy_markdown(path: Path, *, version: str, source: str | None = None) -> PolicyDocument:
    """Load UTF-8 Markdown and keep each H2 rule with all of its H3 descendants."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyKnowledgeError("policy_source_unavailable") from exc
    return load_policy_text(
        raw,
        version=version,
        source=source or path.as_posix(),
        fallback_title=path.name,
    )


def load_policy_text(
    raw: str,
    *,
    version: str,
    source: str,
    fallback_title: str = "knowledge.md",
) -> PolicyDocument:
    """Parse validated Markdown text without requiring a temporary file."""
    if not raw.strip():
        raise PolicyKnowledgeError("policy_source_empty")
    lines = raw.splitlines()
    title = fallback_title
    for line in lines:
        match = HEADING.match(line)
        if match and len(match.group(1)) == 1:
            title = match.group(2).strip()
            break

    groups: list[tuple[str, list[str], list[str]]] = []
    current_section = title
    current_path = [title]
    current_lines: list[str] = []
    for line in lines:
        match = HEADING.match(line)
        if match and len(match.group(1)) == 2:
            if any(item.strip() for item in current_lines):
                groups.append((current_section, current_path, current_lines))
            current_section = match.group(2).strip()
            current_path = [title, current_section]
            current_lines = [line]
        else:
            current_lines.append(line)
    if any(item.strip() for item in current_lines):
        groups.append((current_section, current_path, current_lines))

    source_name = source
    source_sha = _sha256(raw)
    document_id = "policy-doc-" + _sha256(f"{source_name}\0{version}")[:20]
    chunks: list[PolicyChunk] = []
    for ordinal, (section, heading_path, group_lines) in enumerate(groups):
        content = "\n".join(group_lines).strip()
        content_sha = _sha256(content)
        chunk_id = "policy-" + _sha256(f"{version}\0{' / '.join(heading_path)}\0{content_sha}")[:24]
        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                ordinal=ordinal,
                section=section,
                heading_path=heading_path,
                source=source_name,
                version=version,
                content=content,
                content_sha256=content_sha,
            )
        )
    if not chunks:
        raise PolicyKnowledgeError("policy_chunks_empty")
    return PolicyDocument(
        document_id=document_id,
        title=title,
        source=source_name,
        version=version,
        source_sha256=source_sha,
        chunks=chunks,
    )


class PolicyRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _vector_relation(self) -> tuple[str, str]:
        mapping = self.engine.get_execution_options().get("schema_translate_map") or {}
        schema = mapping.get(None) or "public"
        if not isinstance(schema, str) or not SAFE_SCHEMA.fullmatch(schema):
            raise VectorUnavailableError("vector_schema_invalid")
        return schema, f'"{schema}"."policy_chunk_embeddings"'

    def import_document(self, document: PolicyDocument, *, rebuild: bool = False) -> ImportReport:
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db, db.begin():
            row = db.get(PolicyDocumentRow, document.document_id)
            existing_ids = set(
                db.scalars(
                    select(PolicyChunkRow.id).where(
                        PolicyChunkRow.document_id == document.document_id
                    )
                )
            )
            desired_ids = {chunk.chunk_id for chunk in document.chunks}
            if row is not None and row.source_sha256 != document.source_sha256 and not rebuild:
                raise PolicyKnowledgeError("policy_changed_rebuild_required")
            unchanged = (
                row is not None
                and row.source_sha256 == document.source_sha256
                and existing_ids == desired_ids
            )
            if unchanged and not rebuild:
                return ImportReport(
                    document_id=document.document_id,
                    source_sha256=document.source_sha256,
                    chunks=len(document.chunks),
                    inserted=0,
                    unchanged=True,
                    rebuilt=False,
                )
            if row is not None:
                db.execute(
                    delete(PolicyChunkRow).where(PolicyChunkRow.document_id == document.document_id)
                )
                row.source_path = document.source
                row.source_sha256 = document.source_sha256
                row.version = document.version
                row.title = document.title
            else:
                db.add(
                    PolicyDocumentRow(
                        id=document.document_id,
                        source_path=document.source,
                        source_sha256=document.source_sha256,
                        version=document.version,
                        title=document.title,
                    )
                )
            db.flush()
            db.add_all(
                [
                    PolicyChunkRow(
                        id=chunk.chunk_id,
                        document_id=document.document_id,
                        ordinal=chunk.ordinal,
                        section=chunk.section,
                        heading_path=chunk.heading_path,
                        content=chunk.content,
                        content_sha256=chunk.content_sha256,
                    )
                    for chunk in document.chunks
                ]
            )
        return ImportReport(
            document_id=document.document_id,
            source_sha256=document.source_sha256,
            chunks=len(document.chunks),
            inserted=len(document.chunks),
            unchanged=False,
            rebuilt=row is not None,
        )

    def chunks(
        self, *, allowed_source_prefixes: tuple[str, ...] | None = None
    ) -> list[PolicyChunk]:
        query = (
            select(PolicyChunkRow, PolicyDocumentRow)
            .join(PolicyDocumentRow, PolicyDocumentRow.id == PolicyChunkRow.document_id)
            .order_by(PolicyDocumentRow.version, PolicyChunkRow.ordinal)
        )
        if allowed_source_prefixes:
            query = query.where(
                or_(
                    *(
                        PolicyDocumentRow.source_path.startswith(prefix)
                        for prefix in allowed_source_prefixes
                    )
                )
            )
        with Session(self.engine) as db:
            rows = db.execute(query).all()
        return [
            PolicyChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                ordinal=chunk.ordinal,
                section=chunk.section,
                heading_path=list(chunk.heading_path),
                source=document.source_path,
                version=document.version,
                content=chunk.content,
                content_sha256=chunk.content_sha256,
            )
            for chunk, document in rows
        ]

    def delete_document(self, document_id: str) -> bool:
        """Remove one indexed document; chunk and vector rows cascade in PostgreSQL."""
        with Session(self.engine) as db, db.begin():
            row = db.get(PolicyDocumentRow, document_id)
            if row is None:
                return False
            db.delete(row)
        return True

    def ensure_vector_schema(self, dimension: int, *, rebuild: bool = False) -> None:
        if self.engine.dialect.name != "postgresql":
            raise VectorUnavailableError("pgvector_requires_postgresql")
        if dimension < 1 or dimension > 65535:
            raise VectorUnavailableError("embedding_dimension_invalid")
        try:
            schema, relation = self._vector_relation()
            with self.engine.begin() as conn:
                conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
                if rebuild:
                    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {relation}")
                conn.exec_driver_sql(
                    f"CREATE TABLE IF NOT EXISTS {relation} ("
                    f'chunk_id VARCHAR PRIMARY KEY REFERENCES "{schema}".policy_chunks(id) '
                    "ON DELETE CASCADE, "
                    "model VARCHAR NOT NULL, dimension INTEGER NOT NULL, "
                    f"embedding vector({dimension}) NOT NULL)"
                )
                actual = conn.execute(
                    text(
                        "SELECT format_type(a.atttypid, a.atttypmod) "
                        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relname = 'policy_chunk_embeddings' "
                        "AND n.nspname = :schema AND a.attname = 'embedding' "
                        "AND NOT a.attisdropped"
                    ),
                    {"schema": schema},
                ).scalar_one_or_none()
                if actual != f"vector({dimension})":
                    raise VectorUnavailableError("vector_dimension_mismatch_rebuild_required")
        except VectorUnavailableError:
            raise
        except SQLAlchemyError as exc:
            raise VectorUnavailableError("pgvector_extension_unavailable") from exc

    def store_embeddings(
        self,
        vectors: dict[str, list[float]],
        *,
        model: str,
        dimension: int,
    ) -> int:
        if not vectors:
            return 0
        _, relation = self._vector_relation()
        statement = text(
            f"INSERT INTO {relation}(chunk_id, model, dimension, embedding) "
            "VALUES (:chunk_id, :model, :dimension, CAST(:embedding AS vector)) "
            "ON CONFLICT (chunk_id) DO UPDATE SET model=EXCLUDED.model, "
            "dimension=EXCLUDED.dimension, embedding=EXCLUDED.embedding"
        )
        try:
            with self.engine.begin() as conn:
                for chunk_id, vector in vectors.items():
                    conn.execute(
                        statement,
                        {
                            "chunk_id": chunk_id,
                            "model": model,
                            "dimension": dimension,
                            "embedding": _vector_literal(vector, dimension),
                        },
                    )
        except SQLAlchemyError as exc:
            raise VectorUnavailableError("vector_index_write_failed") from exc
        return len(vectors)

    def vector_search(
        self,
        vector: list[float],
        *,
        model: str,
        dimension: int,
        top_k: int,
        allowed_source_prefixes: tuple[str, ...] | None = None,
    ) -> list[SearchHit]:
        schema, relation = self._vector_relation()
        source_filter = ""
        source_parameters: dict[str, str] = {}
        if allowed_source_prefixes:
            clauses = []
            for index, prefix in enumerate(allowed_source_prefixes):
                name = f"source_prefix_{index}"
                clauses.append(f"d.source_path LIKE :{name}")
                source_parameters[name] = prefix + "%"
            source_filter = "AND (" + " OR ".join(clauses) + ") "
        statement = text(
            "SELECT c.id, c.section, c.heading_path, c.content, d.source_path, d.version, "
            "1 - (e.embedding <=> CAST(:embedding AS vector)) AS score "
            f"FROM {relation} e "
            f'JOIN "{schema}".policy_chunks c ON c.id = e.chunk_id '
            f'JOIN "{schema}".policy_documents d ON d.id = c.document_id '
            "WHERE e.model = :model AND e.dimension = :dimension "
            + source_filter
            + "ORDER BY e.embedding <=> CAST(:embedding AS vector) LIMIT :top_k"
        )
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    statement,
                    {
                        "embedding": _vector_literal(vector, dimension),
                        "model": model,
                        "dimension": dimension,
                        "top_k": top_k,
                        **source_parameters,
                    },
                ).mappings()
                return [
                    SearchHit(
                        chunk_id=row["id"],
                        section=row["section"],
                        heading_path=list(row["heading_path"]),
                        source=row["source_path"],
                        version=row["version"],
                        content=row["content"],
                        score=float(row["score"]),
                        retrieval_method="vector",
                    )
                    for row in rows
                ]
        except SQLAlchemyError as exc:
            raise VectorUnavailableError("vector_search_unavailable") from exc


QUERY_CONCEPTS = {
    "cancel": ("cancel", "cancellation", "\u53d6\u6d88", "\u64a4\u9500"),
    "modify": (
        "modify",
        "change",
        "address",
        "payment",
        "\u4fee\u6539",
        "\u66f4\u6539",
        "\u6539\u5730\u5740",
        "\u6539\u6536\u8d27\u5730\u5740",
        "\u652f\u4ed8\u65b9\u5f0f",
        "\u4ed8\u6b3e\u65b9\u5f0f",
    ),
    "return": ("return", "refund", "\u9000\u8d27", "\u9000\u6b3e", "\u9000\u5417"),
    "exchange": (
        "exchange",
        "replace",
        "\u6362\u8d27",
        "\u66f4\u6362",
        "\u4ea4\u6362",
        "\u8c03\u6362",
    ),
    "identity": ("identity", "authenticate", "\u8eab\u4efd", "\u9a8c\u8bc1"),
    "confirmation": ("confirm", "confirmation", "\u786e\u8ba4", "\u540c\u610f"),
    "product": ("product", "item", "variant", "\u5546\u54c1", "\u4ea7\u54c1"),
    "order": ("order", "status", "\u8ba2\u5355", "\u72b6\u6001"),
}

SECTION_HINTS = {
    "Cancel pending order": (
        "cancel",
        "cancellation",
        "\u53d6\u6d88",
        "\u64a4\u9500",
        "\u8bef\u4e0b\u5355",
    ),
    "Modify pending order": (
        "modify",
        "change address",
        "modify item",
        "\u4fee\u6539",
        "\u66f4\u6539",
        "\u6539\u6536\u8d27\u5730\u5740",
        "\u6362\u6210\u793c\u54c1\u5361",
        "\u5546\u54c1\u9009\u9879",
    ),
    "Return delivered order": (
        "return",
        "\u9000\u8d27",
        "\u9000\u5417",
        "\u9000\u8d27\u9000\u6b3e",
    ),
    "Exchange delivered order": (
        "exchange",
        "replace",
        "\u6362\u8d27",
        "\u4ea4\u6362\u5546\u54c1",
        "\u4e0d\u540c\u989c\u8272",
    ),
    "Domain basic": (
        "product id",
        "item id",
        "order statuses",
        "payment methods",
        "\u8ba2\u5355\u53ef\u80fd\u6709\u54ea\u4e9b\u72b6\u6001",
        "\u5c5e\u4e8e\u4ec0\u4e48",
    ),
    "Generic action rules": (
        "generally",
        "acted on",
        "called repeatedly",
        "once per order",
        "\u4e00\u4e2a\u8ba2\u5355\u8c03\u7528\u51e0\u6b21",
    ),
    "Retail agent policy": (
        "authenticate",
        "identity",
        "two different users",
        "human agent",
        "\u6838\u9a8c\u8eab\u4efd",
        "\u8eab\u4efd\u9a8c\u8bc1",
        "\u6570\u636e\u5e93\u5199\u64cd\u4f5c",
        "\u660e\u786e\u786e\u8ba4",
        "\u8f6c\u4eba\u5de5",
        "\u4eba\u5de5\u5ba2\u670d",
    ),
}


def _tokens(value: str) -> set[str]:
    lowered = value.casefold()
    tokens = set(WORDS.findall(lowered))
    for sequence in CJK.findall(lowered):
        tokens.add(sequence)
        tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


def _query_tokens(query: str) -> set[str]:
    tokens = _tokens(query)
    lowered = query.casefold()
    for canonical, aliases in QUERY_CONCEPTS.items():
        if any(alias in lowered for alias in aliases):
            tokens.add(canonical)
            tokens.update(alias for alias in aliases if alias.isascii())
    return tokens


def _section_hints(query: str) -> set[str]:
    lowered = query.casefold()
    return {
        section
        for section, phrases in SECTION_HINTS.items()
        if any(phrase in lowered for phrase in phrases)
    }


class KeywordRetriever:
    """Small deterministic baseline suitable for the current short policy document."""

    def __init__(
        self,
        repository: PolicyRepository,
        *,
        allowed_source_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        self.repository = repository
        self.allowed_source_prefixes = allowed_source_prefixes

    def search(self, query: str, *, top_k: int = 3) -> SearchResult:
        if not query.strip():
            raise PolicyKnowledgeError("policy_query_required")
        if top_k < 1 or top_k > 20:
            raise PolicyKnowledgeError("policy_top_k_invalid")
        started = perf_counter()
        query_terms = _query_tokens(query)
        section_hints = _section_hints(query)
        scored: list[tuple[float, PolicyChunk]] = []
        for chunk in self.repository.chunks(
            allowed_source_prefixes=self.allowed_source_prefixes
        ):
            title_terms = _tokens(" ".join(chunk.heading_path))
            content_terms = _tokens(chunk.content)
            title_overlap = len(query_terms & title_terms)
            body_overlap = len(query_terms & content_terms)
            hint_bonus = 5.0 if chunk.section in section_hints else 0.0
            if not title_overlap and not body_overlap and not hint_bonus:
                continue
            score = (3.0 * title_overlap + body_overlap + hint_bonus) / max(len(query_terms), 1)
            scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].ordinal, item[1].chunk_id))
        hits = [
            SearchHit(
                chunk_id=chunk.chunk_id,
                section=chunk.section,
                heading_path=chunk.heading_path,
                source=chunk.source,
                version=chunk.version,
                content=chunk.content,
                score=round(score, 6),
                retrieval_method="keyword",
            )
            for score, chunk in scored[:top_k]
        ]
        return SearchResult(
            query=query,
            method="keyword",
            top_k=top_k,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            terms=sorted(query_terms),
            hits=hits,
        )


class EmbeddingProvider(Protocol):
    model: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        model: str,
        dimension: int,
        base_url: str,
        api_key: SecretStr | None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if api_key is None or not api_key.get_secret_value():
            raise VectorUnavailableError("embedding_api_key_missing")
        if dimension < 1:
            raise VectorUnavailableError("embedding_dimension_invalid")
        self.model = model
        self.dimension = dimension
        self.url = base_url.rstrip("/") + "/embeddings"
        self.key = api_key.get_secret_value()
        self.timeout = timeout
        self.transport = transport

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        request = {"model": self.model, "input": texts, "dimensions": self.dimension}
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(
                    self.url,
                    json=request,
                    headers={"Authorization": f"Bearer {self.key}"},
                )
                response.raise_for_status()
                payload = response.json()
            ordered = sorted(payload["data"], key=lambda item: int(item["index"]))
            vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if len(vectors) != len(texts) or any(
                len(vector) != self.dimension for vector in vectors
            ):
                raise VectorUnavailableError("embedding_dimension_mismatch")
            return vectors
        except VectorUnavailableError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise VectorUnavailableError("embedding_service_unavailable") from exc


class FastEmbedProvider:
    """Lazy local ONNX embedding provider; vectors are model output, never a mock."""

    def __init__(
        self,
        *,
        model: str,
        dimension: int,
        cache_dir: str,
    ) -> None:
        if dimension < 1:
            raise VectorUnavailableError("embedding_dimension_invalid")
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise VectorUnavailableError("fastembed_dependency_missing") from exc
        try:
            self._embedder = TextEmbedding(model_name=model, cache_dir=cache_dir)
        except Exception as exc:
            raise VectorUnavailableError("fastembed_model_unavailable") from exc
        self.model = f"fastembed:{model}"
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = [vector.astype(float).tolist() for vector in self._embedder.embed(texts)]
        except Exception as exc:
            raise VectorUnavailableError("fastembed_inference_failed") from exc
        if len(vectors) != len(texts) or any(
            len(vector) != self.dimension for vector in vectors
        ):
            raise VectorUnavailableError("embedding_dimension_mismatch")
        return vectors


class VectorRetriever:
    def __init__(
        self,
        repository: PolicyRepository,
        provider: EmbeddingProvider,
        *,
        allowed_source_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.allowed_source_prefixes = allowed_source_prefixes

    def index(self, *, batch_size: int = 32, rebuild: bool = False) -> int:
        if batch_size < 1 or batch_size > 256:
            raise VectorUnavailableError("embedding_batch_size_invalid")
        self.repository.ensure_vector_schema(self.provider.dimension, rebuild=rebuild)
        chunks = self.repository.chunks(allowed_source_prefixes=self.allowed_source_prefixes)
        stored = 0
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            vectors = self.provider.embed([chunk.content for chunk in batch])
            stored += self.repository.store_embeddings(
                dict(zip((chunk.chunk_id for chunk in batch), vectors, strict=True)),
                model=self.provider.model,
                dimension=self.provider.dimension,
            )
        return stored

    def search(self, query: str, *, top_k: int = 3) -> SearchResult:
        if not query.strip():
            raise PolicyKnowledgeError("policy_query_required")
        if top_k < 1 or top_k > 20:
            raise PolicyKnowledgeError("policy_top_k_invalid")
        started = perf_counter()
        self.repository.ensure_vector_schema(self.provider.dimension)
        vector = self.provider.embed([query])[0]
        hits = self.repository.vector_search(
            vector,
            model=self.provider.model,
            dimension=self.provider.dimension,
            top_k=top_k,
            allowed_source_prefixes=self.allowed_source_prefixes,
        )
        return SearchResult(
            query=query,
            method="vector",
            top_k=top_k,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            terms=[],
            hits=hits,
        )


def _vector_literal(values: list[float], dimension: int) -> str:
    if len(values) != dimension or any(not math.isfinite(value) for value in values):
        raise VectorUnavailableError("embedding_dimension_mismatch")
    return "[" + ",".join(format(float(value), ".10g") for value in values) + "]"


def retrieval_result_json(result: SearchResult) -> str:
    """Stable helper for CLI output without leaking provider configuration."""
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
