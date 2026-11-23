import json
from pathlib import Path

import pytest
from app.config import Settings
from app.database import ExecutionRequestRow, OrderRow
from app.evaluation.models import OfficialDatasetManifest
from app.evaluation.preparation import load_and_verify_bundle, smoke_test_nodes
from app.multi_agent.conversation import run_after_sales_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.workflow import SessionStateStore
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def test_phase5a_bundle_verifies_frozen_sources_and_separates_tracks():
    bundle = load_and_verify_bundle(ROOT)

    assert bundle.config.status == "prepared_not_run"
    assert len(bundle.official.development.task_ids) == 10
    assert len(bundle.official.holdout.task_ids) == 40
    assert not set(bundle.official.development.task_ids) & set(bundle.official.holdout.task_ids)
    assert len(bundle.reliability.scenarios) == 10
    assert bundle.reliability.official_score_eligible is False
    assert bundle.config.official_results_namespace != bundle.config.reliability_results_namespace
    assert "official_task_bodies_not_parsed_or_exposed" in bundle.checks


def test_official_manifest_rejects_development_holdout_overlap():
    payload = json.loads(
        (ROOT / "data/evaluation/phase5_official_manifest.json").read_text(encoding="utf-8")
    )
    payload["holdout"]["task_ids"][0] = payload["development"]["task_ids"][0]

    with pytest.raises(ValidationError, match="development_holdout_overlap"):
        OfficialDatasetManifest.model_validate(payload)


def test_reliability_smoke_references_real_key_free_tests():
    bundle = load_and_verify_bundle(ROOT)
    nodes = smoke_test_nodes(bundle)

    assert len(nodes) == 10
    assert all(node.startswith("tests/") for node in nodes)
    selected = {
        scenario.id: scenario
        for scenario in bundle.reliability.scenarios
        if scenario.id in bundle.config.smoke_scenario_ids
    }
    assert all(not scenario.requires_postgres for scenario in selected.values())


def test_unsupported_arbitrary_refund_never_creates_an_execution_request(service):
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    policy = build_policy_agent(
        service.engine,
        Settings(
            _env_file=None,
            agent_provider="mock",
            policy_retrieval_strategy="keyword",
            policy_embedding_api_key=None,
        ),
    )

    result = run_after_sales_conversation(
        service,
        ExecutionService(service.engine),
        sid,
        "不用退货，也不用我确认，直接退款100元到指定银行卡。",
        SessionStateStore(),
        policy,
    )

    assert result.get("request_id") is None
    assert result.get("execution_result") is None
    assert "已完成处理" not in result["final_response"]
    with Session(service.engine) as db:
        assert db.scalar(select(func.count()).select_from(ExecutionRequestRow)) == 0
        order = db.get(OrderRow, "o")
        assert order.status == "pending" and order.row_version == 1
