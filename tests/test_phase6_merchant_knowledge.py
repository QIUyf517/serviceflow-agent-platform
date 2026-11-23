import os
from uuid import uuid4

import pytest
from app.config import Settings
from app.database import engine_for, seed
from app.main import app, get_service
from app.merchant_knowledge import MerchantKnowledgeService
from app.multi_agent.policy_knowledge import FastEmbedProvider, PolicyRepository, VectorRetriever
from app.multi_agent.workflow import SessionStateStore
from app.retail import validate
from fastapi.testclient import TestClient

CONTENT = """# 店铺物流说明

## 默认快递

普通订单通常使用中通或圆通。具体承运商以订单发货后的物流记录为准。

## 发货地点

普通商品一般从杭州仓发出，但会根据库存和收货区域调度仓库。
具体订单的实际发货仓以订单履约信息为准。
"""


def knowledge(service) -> MerchantKnowledgeService:
    return MerchantKnowledgeService(
        service.engine,
        settings=Settings(_env_file=None, policy_retrieval_strategy="keyword"),
    )


def test_draft_publish_search_archive_and_audit(service):
    manager = knowledge(service)
    draft = manager.create_draft(
        "merchant-a",
        "operator-a",
        title="店铺物流说明",
        category="logistics",
        source_label="物流规则",
        version="1.0.0",
        content=CONTENT,
    )
    assert draft["status"] == "draft"
    assert manager.search("merchant-a", "发什么快递")["hits"] == []

    replay = manager.create_draft(
        "merchant-a",
        "operator-a",
        title="店铺物流说明",
        category="logistics",
        source_label="物流规则",
        version="1.0.0",
        content=CONTENT,
    )
    assert replay["id"] == draft["id"]
    assert replay["idempotent_replay"] is True

    published = manager.publish("merchant-a", "operator-a", draft["id"])
    assert published["status"] == "published"
    assert published["chunk_count"] == 3
    assert published["vector_status"] == "not_configured"
    result = manager.search("merchant-a", "一般发什么快递，从哪里发货")
    assert result["hits"]
    assert all(hit["source"].startswith("merchant://merchant-a/") for hit in result["hits"])

    archived = manager.archive("merchant-a", "operator-a", draft["id"])
    assert archived["status"] == "archived"
    assert manager.search("merchant-a", "发什么快递")["hits"] == []
    assert [event["event_type"] for event in manager.audit("merchant-a", draft["id"])] == [
        "draft_created",
        "published",
        "archived",
    ]


def test_published_document_is_immutable_and_tenant_scoped(service):
    manager = knowledge(service)
    draft = manager.create_draft(
        "merchant-a",
        "operator-a",
        title="店铺物流说明",
        category="logistics",
        source_label="物流规则",
        version="1.0.0",
        content=CONTENT,
    )
    manager.publish("merchant-a", "operator-a", draft["id"])

    try:
        manager.update_draft(
            "merchant-a",
            "operator-a",
            draft["id"],
            title="被覆盖",
            category="logistics",
            source_label="物流规则",
            version="1.0.1",
            content=CONTENT + "\n覆盖",
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "knowledge_published_immutable"
    else:
        raise AssertionError("published content must be immutable")

    assert manager.list_documents("merchant-b") == []
    try:
        manager.get("merchant-b", draft["id"])
    except Exception as exc:
        assert getattr(exc, "code", None) == "knowledge_document_not_found"
    else:
        raise AssertionError("cross-merchant access must be hidden")

    other = manager.create_draft(
        "merchant-b",
        "operator-b",
        title="另一商家物流",
        category="logistics",
        source_label="另一商家规则",
        version="1.0.0",
        content="# 另一商家物流\n\n## 特殊承运\n\n仅使用火星专线配送。",
    )
    manager.publish("merchant-b", "operator-b", other["id"])
    assert manager.search("merchant-a", "火星专线")["hits"] == []
    assert manager.search("merchant-b", "火星专线")["hits"][0]["section"] == "特殊承运"


def test_operator_api_publishes_knowledge_used_by_customer_chat(service, monkeypatch):
    import app.main as api

    monkeypatch.setenv("OPERATOR_DEMO_TOKEN", "operator-secret")
    monkeypatch.setenv("MERCHANT_DEMO_ID", "merchant-api")
    monkeypatch.setenv("CUSTOMER_TRIAGE_PROVIDER", "mock")
    monkeypatch.setenv("POLICY_RETRIEVAL_STRATEGY", "keyword")
    monkeypatch.setattr(api, "phase22_store", SessionStateStore())
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    headers = {"x-operator-token": "operator-secret"}
    payload = {
        "title": "店铺物流说明",
        "category": "logistics",
        "source_label": "物流规则",
        "version": "1.0.0",
        "content": CONTENT,
    }
    try:
        assert client.get("/api/v1/merchant/knowledge-documents").status_code == 401
        created = client.post(
            "/api/v1/merchant/knowledge-documents", headers=headers, json=payload
        )
        assert created.status_code == 201
        document_id = created.json()["id"]
        published = client.post(
            f"/api/v1/merchant/knowledge-documents/{document_id}/publish",
            headers=headers,
        )
        assert published.status_code == 200
        assert published.json()["chunk_count"] == 3

        preview = client.get(
            "/api/v1/merchant/knowledge-documents/search",
            headers=headers,
            params={"q": "从哪里发货"},
        )
        assert preview.status_code == 200
        assert preview.json()["hits"]

        sid = client.post("/api/v1/sessions").json()["session_id"]
        answer = client.post(
            "/api/v1/multi-agent/chat",
            headers={"x-session-id": sid},
            json={"message": "你们一般发什么快递，从哪里发货？"},
        )
        assert answer.status_code == 200
        body = answer.json()
        assert body["consultation_route"] == "faq_policy"
        assert "中通或圆通" in body["final_response"]
        assert "杭州仓" in body["final_response"]
        assert "物流规则" in body["final_response"]

        archived = client.post(
            f"/api/v1/merchant/knowledge-documents/{document_id}/archive",
            headers=headers,
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.postgres
def test_real_postgres_pgvector_indexes_and_isolates_merchant_knowledge(sample):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    engine = engine_for(url)
    schema = "phase6_knowledge_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase6-knowledge")
        settings = Settings(
            _env_file=None,
            merchant_demo_id="merchant-vector",
            policy_retrieval_strategy="vector",
            policy_embedding_provider="fastembed",
            policy_local_embedding_cache=".cache/fastembed",
        )
        manager = MerchantKnowledgeService(isolated, settings=settings)
        draft = manager.create_draft(
            "merchant-vector",
            "operator-vector",
            title="店铺物流说明",
            category="logistics",
            source_label="物流规则",
            version="1.0.0",
            content=CONTENT,
        )
        published = manager.publish(
            "merchant-vector", "operator-vector", draft["id"]
        )
        assert published["vector_status"] == "indexed:3"

        provider = FastEmbedProvider(
            model=settings.policy_local_embedding_model,
            dimension=settings.policy_local_embedding_dimensions,
            cache_dir=settings.policy_local_embedding_cache,
        )
        result = VectorRetriever(
            PolicyRepository(isolated),
            provider,
            allowed_source_prefixes=("merchant://merchant-vector/knowledge/",),
        ).search("一般从哪里发货", top_k=3)
        assert result.method == "vector"
        assert result.hits
        assert all(hit.source.startswith("merchant://merchant-vector/") for hit in result.hits)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
