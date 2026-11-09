"""Evaluate real retrieval output; unavailable vector results remain explicitly unavailable."""

import argparse
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter

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
    KeywordRetriever,
    OpenAICompatibleEmbeddingProvider,
    PolicyRepository,
    VectorRetriever,
    VectorUnavailableError,
    load_policy_markdown,
)

DATASET = ROOT / "data/evaluation/policy_retrieval_v1.json"


def _score(retriever, items: list[dict], *, top_k: int, valid_chunks: set[str]) -> dict:
    recalls = []
    reciprocal_ranks = []
    latencies = []
    citation_accuracies = []
    source_integrities = []
    cases = []
    for item in items:
        started = perf_counter()
        result = retriever.search(item["query"], top_k=top_k)
        latency = (perf_counter() - started) * 1000
        sections = [hit.section for hit in result.hits]
        expected = set(item["expected_sections"])
        found = expected.intersection(sections)
        citation_accuracy = (
            sum(section in expected for section in sections) / len(sections)
            if sections
            else 0.0
        )
        source_integrity = (
            sum(hit.chunk_id in valid_chunks for hit in result.hits) / len(result.hits)
            if result.hits
            else 0.0
        )
        recall = len(found) / len(expected)
        rank = next((index + 1 for index, section in enumerate(sections) if section in expected), 0)
        recalls.append(recall)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        latencies.append(latency)
        citation_accuracies.append(citation_accuracy)
        source_integrities.append(source_integrity)
        cases.append(
            {
                "id": item["id"],
                "expected_sections": item["expected_sections"],
                "retrieved_sections": sections,
                "recall_at_3": recall,
                "reciprocal_rank": 1 / rank if rank else 0.0,
                "citation_accuracy_at_3": round(citation_accuracy, 6),
                "citation_source_integrity": round(source_integrity, 6),
                "latency_ms": round(latency, 3),
            }
        )
    return {
        "status": "completed",
        "sample_size": len(items),
        "recall_at_3": round(mean(recalls), 6),
        "mrr": round(mean(reciprocal_ranks), 6),
        "citation_accuracy_at_3": round(mean(citation_accuracies), 6),
        "citation_source_integrity": round(mean(source_integrities), 6),
        "average_latency_ms": round(mean(latencies), 3),
        "cases": cases,
    }


def run(*, attempt_vector: bool = True, top_k: int = 3) -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    items = dataset["items"]
    document = load_policy_markdown(
        ROOT / POLICY_SOURCE,
        version=POLICY_COMMIT,
        source=POLICY_SOURCE.as_posix(),
    )
    with TemporaryDirectory(prefix=".pytest_policy_eval_", dir=ROOT) as directory:
        engine = engine_for(f"sqlite:///{Path(directory, 'policy.db').as_posix()}", testing=True)
        try:
            repository = PolicyRepository(engine)
            repository.import_document(document)
            for demo_document in load_demo_documents():
                repository.import_document(demo_document)
            valid_chunks = {chunk.chunk_id for chunk in repository.chunks()}
            keyword = _score(
                KeywordRetriever(repository),
                items,
                top_k=top_k,
                valid_chunks=valid_chunks,
            )
        finally:
            engine.dispose()
    vector: dict[str, object] = {
        "status": "not_attempted",
        "reason": "vector evaluation disabled",
    }
    if attempt_vector:
        settings = Settings()
        if (
            settings.policy_embedding_provider == "openai_compatible"
            and settings.policy_embedding_api_key is None
        ):
            vector = {"status": "unavailable", "reason": "embedding_api_key_missing"}
        else:
            pg_engine = engine_for(settings.database_url)
            try:
                repository = PolicyRepository(pg_engine)
                repository.import_document(document)
                for demo_document in load_demo_documents():
                    repository.import_document(demo_document)
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
                retriever = VectorRetriever(repository, provider)
                retriever.index(batch_size=settings.policy_embedding_batch_size)
                valid_chunks = {chunk.chunk_id for chunk in repository.chunks()}
                vector = _score(
                    retriever,
                    items,
                    top_k=top_k,
                    valid_chunks=valid_chunks,
                )
                vector.update(
                    embedding_model=provider.model,
                    embedding_dimensions=provider.dimension,
                )
            except VectorUnavailableError as exc:
                vector = {"status": "unavailable", "reason": str(exc)}
            finally:
                pg_engine.dispose()
    return {
        "dataset": dataset["name"],
        "source_version": dataset["source_version"],
        "top_k": top_k,
        "keyword": keyword,
        "vector": vector,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-vector", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(attempt_vector=not args.no_vector)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
