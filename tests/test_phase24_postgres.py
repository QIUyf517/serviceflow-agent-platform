"""Policy import and retrieval in a disposable PostgreSQL schema."""

import os
from uuid import uuid4

import pytest
from app.database import Base, engine_for
from app.multi_agent.policy_agent import POLICY_COMMIT, POLICY_SOURCE, ROOT
from app.multi_agent.policy_knowledge import (
    KeywordRetriever,
    PolicyRepository,
    load_policy_markdown,
)


@pytest.mark.postgres
def test_postgres_policy_import_is_idempotent_and_retrievable():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    engine = engine_for(url)
    schema = "phase24_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        document = load_policy_markdown(
            ROOT / POLICY_SOURCE,
            version=POLICY_COMMIT,
            source=POLICY_SOURCE.as_posix(),
        )
        repository = PolicyRepository(isolated)
        assert repository.import_document(document).inserted == 7
        assert repository.import_document(document).inserted == 0
        result = KeywordRetriever(repository).search("退货政策", top_k=3)
        assert result.hits[0].section == "Return delivered order"
        assert result.hits[0].version == POLICY_COMMIT
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
