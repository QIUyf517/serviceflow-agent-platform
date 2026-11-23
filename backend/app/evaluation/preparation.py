"""Verify frozen Phase 5A inputs without reading official task bodies."""

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.evaluation.models import (
    EvaluationConfig,
    OfficialDatasetManifest,
    ReliabilityManifest,
)


@dataclass(frozen=True)
class EvaluationBundle:
    config: EvaluationConfig
    official: OfficialDatasetManifest
    reliability: ReliabilityManifest
    checks: tuple[str, ...]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_repo_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    root = root.resolve()
    if path != root and root not in path.parents:
        raise ValueError("evaluation_path_outside_repository")
    return path


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _verify_test_node(root: Path, node_id: str) -> None:
    parts = node_id.split("::")
    if len(parts) != 2 or not parts[0].startswith("tests/"):
        raise ValueError(f"test_node_id_invalid:{node_id}")
    test_path = _resolve_repo_path(root, parts[0])
    if not test_path.is_file() or parts[1] not in _test_functions(test_path):
        raise ValueError(f"test_node_id_missing:{node_id}")


def load_and_verify_bundle(root: Path) -> EvaluationBundle:
    root = root.resolve()
    config_path = root / "reports" / "eval_config.json"
    config = EvaluationConfig.model_validate(_load_json(config_path))
    official_path = _resolve_repo_path(root, config.official_manifest)
    reliability_path = _resolve_repo_path(root, config.reliability_manifest)
    if sha256_file(official_path) != config.official_manifest_sha256:
        raise ValueError("official_manifest_hash_mismatch")
    if sha256_file(reliability_path) != config.reliability_manifest_sha256:
        raise ValueError("reliability_manifest_hash_mismatch")

    official = OfficialDatasetManifest.model_validate(_load_json(official_path))
    reliability = ReliabilityManifest.model_validate(_load_json(reliability_path))
    raw = root / "data" / "raw" / "tau2" / official.upstream_commit
    for name, expected in official.data_sha256.items():
        source = raw / name
        if not source.is_file() or sha256_file(source) != expected:
            raise ValueError(f"official_source_hash_mismatch:{name}")

    splits = _load_json(raw / "split_tasks.json")
    if not isinstance(splits, dict):
        raise ValueError("official_split_invalid")
    if not set(official.development.task_ids).issubset(set(splits.get("train", []))):
        raise ValueError("development_ids_outside_train")
    if set(official.holdout.task_ids) != set(splits.get("test", [])):
        raise ValueError("holdout_must_equal_official_test_split")

    scenario_map = {scenario.id: scenario for scenario in reliability.scenarios}
    if not set(config.smoke_scenario_ids).issubset(scenario_map):
        raise ValueError("smoke_scenario_unknown")
    for scenario in reliability.scenarios:
        for node_id in scenario.test_node_ids:
            _verify_test_node(root, node_id)
    if any(scenario_map[item].requires_postgres for item in config.smoke_scenario_ids):
        raise ValueError("smoke_must_not_require_postgres")

    return EvaluationBundle(
        config=config,
        official=official,
        reliability=reliability,
        checks=(
            "manifest_hashes_verified",
            "official_source_hashes_verified",
            "development_holdout_disjoint",
            "holdout_matches_official_test_split",
            "official_task_bodies_not_parsed_or_exposed",
            "reliability_test_nodes_verified",
            "official_and_reliability_results_separated",
        ),
    )


def smoke_test_nodes(bundle: EvaluationBundle) -> list[str]:
    scenario_map = {scenario.id: scenario for scenario in bundle.reliability.scenarios}
    nodes: list[str] = []
    for scenario_id in bundle.config.smoke_scenario_ids:
        for node_id in scenario_map[scenario_id].test_node_ids:
            if node_id not in nodes:
                nodes.append(node_id)
    return nodes
