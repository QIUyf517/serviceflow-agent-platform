"""Idempotently import the pinned Retail policy and optionally build pgvector embeddings."""

import argparse
import json

from app.config import Settings
from app.database import engine_for
from app.multi_agent.policy_agent import (
    POLICY_COMMIT,
    POLICY_SOURCE,
    ROOT,
    load_demo_documents,
)
from app.multi_agent.policy_knowledge import (
    FastEmbedProvider,
    OpenAICompatibleEmbeddingProvider,
    PolicyKnowledgeError,
    PolicyRepository,
    VectorRetriever,
    load_policy_markdown,
)


def run(*, rebuild: bool = False, vector: bool = False, rebuild_vector: bool = False) -> dict:
    settings = Settings()
    source = ROOT / POLICY_SOURCE
    manifest_path = source.parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyKnowledgeError("policy_manifest_invalid") from exc
    document = load_policy_markdown(
        source,
        version=POLICY_COMMIT,
        source=POLICY_SOURCE.as_posix(),
    )
    expected = manifest.get("files", {}).get("policy.md", {}).get("sha256")
    if manifest.get("commit") != POLICY_COMMIT or expected != document.source_sha256:
        raise PolicyKnowledgeError("policy_source_hash_mismatch")
    engine = engine_for(settings.database_url)
    try:
        repository = PolicyRepository(engine)
        imported = repository.import_document(document, rebuild=rebuild)
        demo_reports = [
            repository.import_document(item, rebuild=rebuild).model_dump()
            for item in load_demo_documents()
        ]
        result: dict[str, object] = {
            "keyword_index": "ready",
            "document_id": imported.document_id,
            "source_sha256": imported.source_sha256,
            "chunks": imported.chunks,
            "inserted": imported.inserted,
            "unchanged": imported.unchanged,
            "rebuilt": imported.rebuilt,
            "vector_index": "not_requested",
            "demo_documents": demo_reports,
        }
        if vector:
            if settings.policy_embedding_provider == "fastembed":
                provider = FastEmbedProvider(
                    model=settings.policy_local_embedding_model,
                    dimension=settings.policy_local_embedding_dimensions,
                    cache_dir=settings.policy_local_embedding_cache,
                )
            else:
                provider = OpenAICompatibleEmbeddingProvider(
                    model=settings.policy_embedding_model,
                    dimension=settings.policy_embedding_dimensions,
                    base_url=settings.policy_embedding_base_url,
                    api_key=settings.policy_embedding_api_key,
                    timeout=settings.agent_timeout_seconds,
                )
            count = VectorRetriever(repository, provider).index(
                batch_size=settings.policy_embedding_batch_size,
                rebuild=rebuild_vector,
            )
            result.update(
                vector_index="ready",
                embedded_chunks=count,
                embedding_model=provider.model,
                embedding_dimensions=provider.dimension,
            )
        return result
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--vector", action="store_true")
    parser.add_argument("--rebuild-vector", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run(
                    rebuild=args.rebuild,
                    vector=args.vector,
                    rebuild_vector=args.rebuild_vector,
                ),
                ensure_ascii=False,
            )
        )
    except PolicyKnowledgeError as exc:
        print(json.dumps({"status": "failed", "code": str(exc)}))
        raise SystemExit(1) from None
