"""Typed contracts for the AV2 judge pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PanelMode = Literal["single", "primary_only", "2plus1"]
JudgeProvider = Literal["remote_http"]
JudgeRole = Literal["single", "primary", "arbiter"]
StoredJudgeRole = Literal["principal", "controle", "arbitro"]
JudgeExecutionStrategy = Literal["sequential", "parallel"]

PROMPT_VERSION = "av2-judge-v1"
RUBRIC_VERSION = "av2-legal-rubric-v1"


@dataclass(frozen=True)
class ModelSpec:
    """Resolved judge model identity."""

    requested: str
    provider_model: str


@dataclass(frozen=True)
class JudgeSettings:
    """Settings loaded from ``.env`` and process environment."""

    database_url: str
    judge_provider: JudgeProvider
    remote_judge_base_url: str | None
    remote_judge_api_key: str | None
    judge_panel_mode: PanelMode
    remote_judge_default_model: str | None
    remote_primary_judge_panel: tuple[str, ...]
    remote_arbiter_judge_model: str | None
    judge_arbitration_min_delta: int
    judge_always_run_arbiter: bool
    remote_judge_timeout_seconds: int
    remote_judge_temperature: float
    remote_judge_max_tokens: int
    remote_judge_top_p: float
    remote_judge_openai_compatible: bool
    judge_save_raw_response: bool
    judge_execution_strategy: JudgeExecutionStrategy


@dataclass(frozen=True)
class RuntimeJudgeConfig:
    """Effective judge execution config after CLI overrides are applied."""

    provider: JudgeProvider
    panel_mode: PanelMode
    single_judge: ModelSpec | None
    primary_panel: tuple[ModelSpec, ...]
    arbiter: ModelSpec | None
    arbitration_min_delta: int
    always_run_arbiter: bool
    execution_strategy: JudgeExecutionStrategy
    settings: JudgeSettings
    model_source: str


@dataclass(frozen=True)
class CandidateAnswerContext:
    """Question, reference, and AV1 answer loaded from PostgreSQL."""

    answer_id: int
    question_id: int
    dataset_name: str
    question_text: str
    reference_answer: str
    candidate_answer: str
    candidate_model: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeRawResponse:
    """Raw remote judge response plus provider metadata."""

    text: str
    provider: str
    model: str
    latency_ms: int
    status_code: int | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class ParsedJudgeEvaluation:
    """Structured, validated judge evaluation."""

    score: int
    rationale: str
    legal_accuracy: str | None = None
    hallucination_risk: str | None = None
    rubric_alignment: str | None = None
    requires_human_review: bool = False
    criteria: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRecord:
    """Evaluation row prepared for persistence."""

    answer_id: int
    judge_model: ModelSpec
    stored_role: StoredJudgeRole
    panel_mode: PanelMode
    trigger_reason: str
    score: int
    rationale: str
    prompt: str
    rubric: str
    latency_ms: int
    raw_response: JudgeRawResponse | None = None


@dataclass(frozen=True)
class PipelineSummary:
    """Concise run result for CLI reporting."""

    selected_answers: int
    executed_evaluations: int
    skipped_evaluations: int
    arbiter_evaluations: int
