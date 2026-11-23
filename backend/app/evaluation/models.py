"""Strict, versioned models for evaluation inputs prepared in Phase 5A."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetSlice(StrictModel):
    access: Literal["development", "holdout"]
    source_split: Literal["train", "test"]
    task_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_task_ids(self) -> "DatasetSlice":
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("duplicate_task_id")
        if any(not task_id.isdigit() for task_id in self.task_ids):
            raise ValueError("task_id_must_be_numeric")
        return self


class HoldoutPolicy(StrictModel):
    phase5a_task_body_access: Literal["prohibited"]
    prompt_tuning_allowed: Literal[False]
    agent_runtime_evaluation_criteria_access: Literal[False]
    first_scored_use: Literal["phase5b"]


class OfficialDatasetManifest(StrictModel):
    schema_version: Literal["1.0"]
    kind: Literal["official_tau2_retail"]
    upstream_repository: str
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    data_sha256: dict[str, str]
    development: DatasetSlice
    holdout: DatasetSlice
    holdout_policy: HoldoutPolicy

    @model_validator(mode="after")
    def validate_boundaries(self) -> "OfficialDatasetManifest":
        if self.development.access != "development" or self.development.source_split != "train":
            raise ValueError("development_must_use_train_split")
        if self.holdout.access != "holdout" or self.holdout.source_split != "test":
            raise ValueError("holdout_must_use_test_split")
        if set(self.development.task_ids) & set(self.holdout.task_ids):
            raise ValueError("development_holdout_overlap")
        required = {"db.json", "policy.md", "tasks.json", "split_tasks.json"}
        if set(self.data_sha256) != required:
            raise ValueError("official_hash_set_invalid")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.data_sha256.values()
        ):
            raise ValueError("official_hash_invalid")
        return self


class ReliabilityScenario(StrictModel):
    id: str = Field(pattern=r"^REL-[0-9]{3}$")
    category: Literal[
        "identity",
        "authorization",
        "confirmation",
        "policy",
        "binding",
        "idempotency",
        "state_change",
        "recovery",
        "unsupported_action",
        "prompt_injection",
    ]
    title: str = Field(min_length=1)
    stimulus: str = Field(min_length=1)
    expected_outcomes: list[str] = Field(min_length=1)
    expected_metrics: dict[str, int | float | bool] = Field(min_length=1)
    test_node_ids: list[str] = Field(min_length=1)
    requires_postgres: bool = False


class ReliabilityManifest(StrictModel):
    schema_version: Literal["1.0"]
    kind: Literal["serviceflow_reliability"]
    version: str
    authored_source: Literal["serviceflow"]
    official_score_eligible: Literal[False]
    contains_official_task_content: Literal[False]
    scenarios: list[ReliabilityScenario] = Field(min_length=10)

    @model_validator(mode="after")
    def validate_scenarios(self) -> "ReliabilityManifest":
        ids = [scenario.id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_scenario_id")
        categories = [scenario.category for scenario in self.scenarios]
        if len(categories) != len(set(categories)):
            raise ValueError("reliability_categories_must_be_unique")
        return self


class ExperimentArm(StrictModel):
    id: Literal["rules", "single_agent", "multi_agent", "multi_agent_recovery"]
    tracks: list[Literal["official_tasks_custom_judge", "reliability"]] = Field(min_length=1)
    guard_profile: str
    tool_contract: str


class FormalRunSettings(StrictModel):
    provider: Literal["openai_compatible"]
    model: str
    official_agent_model_alias: str
    user_simulator_model: str
    semantic_judge_provider: Literal["deepseek"]
    semantic_judge_model: str
    scoring_profile: Literal["tau2_semantic_prompt_deepseek_judge"]
    temperature: float = Field(ge=0)
    seed: int | None
    task_seed: int
    num_trials: int = Field(ge=1)
    max_steps: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    max_concurrency: int = Field(ge=1)
    pricing_basis: Literal["record_at_run_time"]


class EvaluationConfig(StrictModel):
    schema_version: Literal["1.0"]
    phase: Literal["5A"]
    status: Literal["prepared_not_run"]
    official_manifest: str
    official_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reliability_manifest: str
    reliability_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_results_namespace: str
    reliability_results_namespace: str
    smoke_provider: Literal["mock"]
    smoke_scenario_ids: list[str] = Field(min_length=1)
    formal: FormalRunSettings
    arms: list[ExperimentArm] = Field(min_length=4, max_length=4)
    notes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_comparison_contract(self) -> "EvaluationConfig":
        if self.official_results_namespace == self.reliability_results_namespace:
            raise ValueError("result_namespaces_must_be_separate")
        arm_ids = [arm.id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)) or set(arm_ids) != {
            "rules",
            "single_agent",
            "multi_agent",
            "multi_agent_recovery",
        }:
            raise ValueError("comparison_arms_invalid")
        if len(self.smoke_scenario_ids) != len(set(self.smoke_scenario_ids)):
            raise ValueError("duplicate_smoke_scenario")
        return self
