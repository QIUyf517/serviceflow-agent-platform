"""Merchant-managed, versioned knowledge sources for the shared RAG index."""

from __future__ import annotations

import hashlib
from time import time
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import (
    MerchantKnowledgeAuditRow,
    MerchantKnowledgeDocumentRow,
    PolicyChunkRow,
    PolicyDocumentRow,
)
from app.multi_agent.policy_knowledge import (
    FastEmbedProvider,
    KeywordRetriever,
    OpenAICompatibleEmbeddingProvider,
    PolicyRepository,
    VectorRetriever,
    VectorUnavailableError,
    load_policy_text,
)
from app.service import BusinessError

ALLOWED_CATEGORIES = {"logistics", "faq", "product_guide", "service_notice"}
MAX_CONTENT_CHARS = 100_000


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_markdown(title: str, content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise BusinessError("knowledge_content_required", 422)
    if len(normalized) > MAX_CONTENT_CHARS:
        raise BusinessError("knowledge_content_too_large", 422)
    if not any(line.startswith("# ") for line in normalized.splitlines()):
        normalized = f"# {title.strip()}\n\n{normalized}"
    return normalized + "\n"


class MerchantKnowledgeService:
    """Manage one server-bound merchant's sources without trusting client tenant IDs."""

    def __init__(self, engine: Engine, *, settings: Settings | None = None) -> None:
        self.engine = engine
        self.settings = settings or Settings()

    @staticmethod
    def _row(db: Session, merchant_id: str, document_id: str) -> MerchantKnowledgeDocumentRow:
        row = db.scalar(
            select(MerchantKnowledgeDocumentRow).where(
                MerchantKnowledgeDocumentRow.id == document_id,
                MerchantKnowledgeDocumentRow.merchant_id == merchant_id,
            )
        )
        if row is None:
            raise BusinessError("knowledge_document_not_found", 404)
        return row

    @staticmethod
    def _audit(
        db: Session,
        row: MerchantKnowledgeDocumentRow,
        actor_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        db.add(
            MerchantKnowledgeAuditRow(
                id=uuid4().hex,
                merchant_id=row.merchant_id,
                document_id=row.id,
                event_type=event_type,
                actor_id=actor_id,
                payload=payload,
                created_at=int(time()),
            )
        )

    @staticmethod
    def _projection(row: MerchantKnowledgeDocumentRow, chunk_count: int = 0) -> dict[str, Any]:
        return {
            "id": row.id,
            "merchant_id": row.merchant_id,
            "title": row.title,
            "category": row.category,
            "source_label": row.source_label,
            "version": row.version,
            "status": row.status,
            "content": row.content,
            "content_sha256": row.content_sha256,
            "chunk_count": chunk_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "published_at": row.published_at,
            "archived_at": row.archived_at,
        }

    def create_draft(
        self,
        merchant_id: str,
        actor_id: str,
        *,
        title: str,
        category: str,
        source_label: str,
        version: str,
        content: str,
    ) -> dict[str, Any]:
        if category not in ALLOWED_CATEGORIES:
            raise BusinessError("knowledge_category_invalid", 422)
        markdown = _normalized_markdown(title, content)
        digest = _sha256(markdown)
        now = int(time())
        try:
            with Session(self.engine) as db, db.begin():
                existing = db.scalar(
                    select(MerchantKnowledgeDocumentRow).where(
                        MerchantKnowledgeDocumentRow.merchant_id == merchant_id,
                        MerchantKnowledgeDocumentRow.content_sha256 == digest,
                    )
                )
                if existing is not None:
                    result = self._projection(existing, self._chunk_count(db, existing))
                    result["idempotent_replay"] = True
                    return result
                row = MerchantKnowledgeDocumentRow(
                    id=uuid4().hex,
                    merchant_id=merchant_id,
                    title=title.strip(),
                    category=category,
                    source_label=source_label.strip(),
                    version=version.strip(),
                    status="draft",
                    content=markdown,
                    content_sha256=digest,
                    policy_document_id=None,
                    created_by=actor_id,
                    created_at=now,
                    updated_at=now,
                    published_at=None,
                    archived_at=None,
                )
                db.add(row)
                db.flush()
                self._audit(db, row, actor_id, "draft_created", {"category": category})
                result = self._projection(row)
            return result
        except IntegrityError as exc:
            raise BusinessError("knowledge_document_conflict", 409) from exc

    def update_draft(
        self,
        merchant_id: str,
        actor_id: str,
        document_id: str,
        *,
        title: str,
        category: str,
        source_label: str,
        version: str,
        content: str,
    ) -> dict[str, Any]:
        if category not in ALLOWED_CATEGORIES:
            raise BusinessError("knowledge_category_invalid", 422)
        markdown = _normalized_markdown(title, content)
        digest = _sha256(markdown)
        with Session(self.engine) as db, db.begin():
            row = self._row(db, merchant_id, document_id)
            if row.status != "draft":
                raise BusinessError("knowledge_published_immutable", 409)
            duplicate = db.scalar(
                select(MerchantKnowledgeDocumentRow.id).where(
                    MerchantKnowledgeDocumentRow.merchant_id == merchant_id,
                    MerchantKnowledgeDocumentRow.content_sha256 == digest,
                    MerchantKnowledgeDocumentRow.id != document_id,
                )
            )
            if duplicate is not None:
                raise BusinessError("knowledge_document_conflict", 409)
            row.title = title.strip()
            row.category = category
            row.source_label = source_label.strip()
            row.version = version.strip()
            row.content = markdown
            row.content_sha256 = digest
            row.updated_at = int(time())
            self._audit(db, row, actor_id, "draft_updated", {"category": category})
            return self._projection(row)

    @staticmethod
    def _chunk_count(db: Session, row: MerchantKnowledgeDocumentRow) -> int:
        if row.policy_document_id is None:
            return 0
        return int(
            db.scalar(
                select(func.count()).select_from(PolicyChunkRow).where(
                    PolicyChunkRow.document_id == row.policy_document_id
                )
            )
            or 0
        )

    def list_documents(self, merchant_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as db:
            rows = list(
                db.scalars(
                    select(MerchantKnowledgeDocumentRow)
                    .where(MerchantKnowledgeDocumentRow.merchant_id == merchant_id)
                    .order_by(MerchantKnowledgeDocumentRow.updated_at.desc())
                )
            )
            return [self._projection(row, self._chunk_count(db, row)) for row in rows]

    def publish(self, merchant_id: str, actor_id: str, document_id: str) -> dict[str, Any]:
        with Session(self.engine) as db, db.begin():
            row = self._row(db, merchant_id, document_id)
            if row.status == "published":
                result = self._projection(row, self._chunk_count(db, row))
                result.update(idempotent_replay=True, vector_status="unchanged")
                return result
            if row.status != "draft":
                raise BusinessError("knowledge_document_not_publishable", 409)
            source = f"merchant://{merchant_id}/knowledge/{row.id}/{row.source_label}"
            document = load_policy_text(
                row.content,
                version=f"merchant/{row.version}/{row.content_sha256[:12]}",
                source=source,
                fallback_title=row.title,
            )
            if db.get(PolicyDocumentRow, document.document_id) is not None:
                raise BusinessError("knowledge_index_conflict", 409)
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
            now = int(time())
            row.policy_document_id = document.document_id
            row.status = "published"
            row.published_at = now
            row.updated_at = now
            self._audit(
                db,
                row,
                actor_id,
                "published",
                {"chunk_count": len(document.chunks), "source": source},
            )
        result = self.get(merchant_id, document_id)
        result["vector_status"] = self._index_vectors_if_configured()
        return result

    def _index_vectors_if_configured(self) -> str:
        if self.settings.policy_retrieval_strategy == "keyword":
            return "not_configured"
        try:
            if self.settings.policy_embedding_provider == "fastembed":
                provider = FastEmbedProvider(
                    model=self.settings.policy_local_embedding_model,
                    dimension=self.settings.policy_local_embedding_dimensions,
                    cache_dir=self.settings.policy_local_embedding_cache,
                )
            elif self.settings.policy_embedding_api_key is not None:
                provider = OpenAICompatibleEmbeddingProvider(
                    model=self.settings.policy_embedding_model,
                    dimension=self.settings.policy_embedding_dimensions,
                    base_url=self.settings.policy_embedding_base_url,
                    api_key=self.settings.policy_embedding_api_key,
                    timeout=self.settings.agent_timeout_seconds,
                )
            else:
                return "provider_unavailable"
            count = VectorRetriever(PolicyRepository(self.engine), provider).index(
                batch_size=self.settings.policy_embedding_batch_size
            )
            return f"indexed:{count}"
        except VectorUnavailableError as exc:
            return f"unavailable:{exc}"

    def get(self, merchant_id: str, document_id: str) -> dict[str, Any]:
        with Session(self.engine) as db:
            row = self._row(db, merchant_id, document_id)
            return self._projection(row, self._chunk_count(db, row))

    def archive(self, merchant_id: str, actor_id: str, document_id: str) -> dict[str, Any]:
        with Session(self.engine) as db, db.begin():
            row = self._row(db, merchant_id, document_id)
            if row.status == "archived":
                result = self._projection(row)
                result["idempotent_replay"] = True
                return result
            if row.policy_document_id is not None:
                indexed = db.get(PolicyDocumentRow, row.policy_document_id)
                row.policy_document_id = None
                db.flush()
                if indexed is not None:
                    db.delete(indexed)
            now = int(time())
            row.status = "archived"
            row.archived_at = now
            row.updated_at = now
            self._audit(db, row, actor_id, "archived", {})
            return self._projection(row)

    def search(self, merchant_id: str, query: str, *, top_k: int = 5) -> dict[str, Any]:
        prefix = f"merchant://{merchant_id}/knowledge/"
        result = KeywordRetriever(
            PolicyRepository(self.engine), allowed_source_prefixes=(prefix,)
        ).search(query, top_k=top_k)
        hits = result.hits
        return {
            "query": query,
            "method": result.method,
            "hits": [hit.model_dump() for hit in hits],
        }

    def audit(self, merchant_id: str, document_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as db:
            self._row(db, merchant_id, document_id)
            rows = list(
                db.scalars(
                    select(MerchantKnowledgeAuditRow)
                    .where(
                        MerchantKnowledgeAuditRow.merchant_id == merchant_id,
                        MerchantKnowledgeAuditRow.document_id == document_id,
                    )
                    .order_by(MerchantKnowledgeAuditRow.created_at, MerchantKnowledgeAuditRow.id)
                )
            )
            events = [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "actor_id": row.actor_id,
                    "payload": row.payload,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            rank = {"draft_created": 0, "draft_updated": 1, "published": 2, "archived": 3}
            return sorted(
                events,
                key=lambda event: (event["created_at"], rank[event["event_type"]]),
            )
