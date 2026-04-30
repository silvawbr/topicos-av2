"""Judge pipeline orchestration and execution-mode policy."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from .audit import AuditEvent, NullAuditLogger
from .contracts import (
    CandidateAnswerContext,
    EvaluationRecord,
    ModelSpec,
    PipelineSummary,
    RuntimeJudgeConfig,
    StoredJudgeRole,
)
from .judge_clients.base import JudgeClient
from .parser import parse_judge_output
from .prompts import build_judge_prompt
from .repositories import JudgeRepositoryProtocol


class JudgePipeline:
    """Local orchestration for remote judge execution."""

    def __init__(
        self,
        repository: JudgeRepositoryProtocol,
        client: JudgeClient,
        audit: NullAuditLogger | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self.audit = audit or NullAuditLogger()

    def run(
        self,
        answers: Sequence[CandidateAnswerContext],
        config: RuntimeJudgeConfig,
    ) -> PipelineSummary:
        executed = 0
        skipped = 0
        arbiters = 0

        for answer in answers:
            self.audit.terminal_event(f"Running answer {answer.answer_id} ({answer.dataset_name})")
            self.audit.event(
                AuditEvent(
                    "answer_started",
                    (
                        f"answer_id={answer.answer_id} question_id={answer.question_id} "
                        f"dataset={answer.dataset_name} candidate_model={answer.candidate_model}"
                    ),
                )
            )
            result = self._run_answer(answer, config)
            executed += result.executed_evaluations
            skipped += result.skipped_evaluations
            arbiters += result.arbiter_evaluations
            self.audit.event(
                AuditEvent(
                    "answer_finished",
                    (
                        f"answer_id={answer.answer_id} executed={result.executed_evaluations} "
                        f"skipped={result.skipped_evaluations} arbiters={result.arbiter_evaluations}"
                    ),
                )
            )

        return PipelineSummary(
            selected_answers=len(answers),
            executed_evaluations=executed,
            skipped_evaluations=skipped,
            arbiter_evaluations=arbiters,
        )

    def _run_answer(self, answer: CandidateAnswerContext, config: RuntimeJudgeConfig) -> PipelineSummary:
        if config.panel_mode == "single":
            assert config.single_judge is not None
            executed, skipped = self._execute_if_needed(
                answer=answer,
                config=config,
                judge_model=config.single_judge,
                stored_role="principal",
                trigger_reason="single_mode",
            )
            return PipelineSummary(1, executed, skipped, 0)

        primary_scores: list[int] = []
        executed = 0
        skipped = 0
        roles: tuple[StoredJudgeRole, ...] = ("principal", "controle")
        pending: list[tuple[ModelSpec, StoredJudgeRole]] = []
        for judge_model, stored_role in zip(config.primary_panel, roles, strict=False):
            score_before = self.repository.existing_score(
                answer.answer_id,
                judge_model,
                stored_role,
                config.panel_mode,
            )
            if score_before is not None:
                skipped += 1
                primary_scores.append(score_before)
                self.audit.terminal_event(
                    f"Skipping answer {answer.answer_id} for {judge_model.requested}: existing evaluation"
                )
                self.audit.event(
                    AuditEvent(
                        "evaluation_skipped",
                        (
                            f"answer_id={answer.answer_id} model={judge_model.provider_model} "
                            f"role={stored_role} mode={config.panel_mode} existing_score={score_before}"
                        ),
                    )
                )
                continue
            pending.append((judge_model, stored_role))

        records = self._execute_primary_judges(answer, config, pending)
        for record in records:
            with self.audit.step(
                f"Persisting evaluation for answer {answer.answer_id}",
                detail=(
                    f"answer_id={answer.answer_id} model={record.judge_model.provider_model} "
                    f"role={record.stored_role} score={record.score}"
                ),
            ):
                self.repository.persist_evaluation(record)
            executed += 1
            primary_scores.append(record.score)

        if config.panel_mode == "primary_only":
            return PipelineSummary(1, executed, skipped, 0)

        if len(primary_scores) != 2:
            return PipelineSummary(1, executed, skipped, 0)

        score_delta = abs(primary_scores[0] - primary_scores[1])
        arbiter_reason = _arbiter_reason(config, score_delta)
        if arbiter_reason is None:
            self.audit.terminal_event(
                f"Arbiter skipped for answer {answer.answer_id}: score delta {score_delta}"
            )
            self.audit.event(
                AuditEvent(
                    "arbiter_skipped",
                    (
                        f"answer_id={answer.answer_id} score_delta={score_delta} "
                        f"threshold={config.arbitration_min_delta}"
                    ),
                )
            )
            return PipelineSummary(1, executed, skipped, 0)

        assert config.arbiter is not None
        arbiter_executed, arbiter_skipped = self._execute_if_needed(
            answer=answer,
            config=config,
            judge_model=config.arbiter,
            stored_role="arbitro",
            trigger_reason=arbiter_reason,
        )
        return PipelineSummary(1, executed + arbiter_executed, skipped + arbiter_skipped, arbiter_executed)

    def _execute_if_needed(
        self,
        *,
        answer: CandidateAnswerContext,
        config: RuntimeJudgeConfig,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        trigger_reason: str,
    ) -> tuple[int, int]:
        if self.repository.evaluation_exists(
            answer.answer_id,
            judge_model,
            stored_role,
            config.panel_mode,
        ):
            self.audit.terminal_event(
                f"Skipping answer {answer.answer_id} for {judge_model.requested}: existing evaluation"
            )
            self.audit.event(
                AuditEvent(
                    "evaluation_skipped",
                    (
                        f"answer_id={answer.answer_id} model={judge_model.provider_model} "
                        f"role={stored_role} mode={config.panel_mode}"
                    ),
                )
            )
            return 0, 1
        record = self._execute_judge(
            answer=answer,
            config=config,
            judge_model=judge_model,
            stored_role=stored_role,
            trigger_reason=trigger_reason,
        )
        with self.audit.step(
            f"Persisting evaluation for answer {answer.answer_id}",
            detail=(
                f"answer_id={answer.answer_id} model={judge_model.provider_model} "
                f"role={stored_role} score={record.score}"
            ),
        ):
            self.repository.persist_evaluation(record)
        return 1, 0

    def _execute_judge(
        self,
        *,
        answer: CandidateAnswerContext,
        config: RuntimeJudgeConfig,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        trigger_reason: str,
        terminal_progress: bool = True,
    ) -> EvaluationRecord:
        prompt = build_judge_prompt(answer)
        detail = (
            f"answer_id={answer.answer_id} question_id={answer.question_id} "
            f"model={judge_model.provider_model} role={stored_role} trigger={trigger_reason}"
        )
        with self.audit.step(
            f"Running answer {answer.answer_id} with {judge_model.requested}",
            detail=detail,
            terminal=terminal_progress,
        ):
            raw_response = self.client.judge(prompt=prompt, model=judge_model.provider_model)
        with self.audit.step(
            f"Parsing judge response for answer {answer.answer_id}",
            detail=detail,
            terminal=terminal_progress,
        ):
            parsed = parse_judge_output(raw_response.text)
        self.audit.event(
            AuditEvent(
                "evaluation_parsed",
                (
                    f"{detail} score={parsed.score} latency_ms={raw_response.latency_ms} "
                    f"status_code={raw_response.status_code}"
                ),
            )
        )
        return EvaluationRecord(
            answer_id=answer.answer_id,
            judge_model=judge_model,
            stored_role=stored_role,
            panel_mode=config.panel_mode,
            trigger_reason=trigger_reason,
            score=parsed.score,
            rationale=parsed.rationale,
            prompt=prompt,
            rubric=answer.reference_answer,
            latency_ms=raw_response.latency_ms,
            raw_response=raw_response,
        )

    def _execute_primary_judges(
        self,
        answer: CandidateAnswerContext,
        config: RuntimeJudgeConfig,
        pending: Sequence[tuple[ModelSpec, StoredJudgeRole]],
    ) -> list[EvaluationRecord]:
        if not pending:
            return []
        if config.execution_strategy == "sequential" or len(pending) == 1:
            self.audit.event(
                AuditEvent(
                    "judge_execution_strategy",
                    f"answer_id={answer.answer_id} strategy=sequential calls={len(pending)}",
                )
            )
            return [
                self._execute_judge(
                    answer=answer,
                    config=config,
                    judge_model=judge_model,
                    stored_role=stored_role,
                    trigger_reason="primary_panel",
                )
                for judge_model, stored_role in pending
            ]

        self.audit.event(
            AuditEvent(
                "judge_execution_strategy",
                f"answer_id={answer.answer_id} strategy=parallel calls={len(pending)}",
            )
        )
        with self.audit.step(
            f"Running {len(pending)} primary judges in parallel for answer {answer.answer_id}",
            detail=f"answer_id={answer.answer_id} models={','.join(model.provider_model for model, _ in pending)}",
        ):
            with ThreadPoolExecutor(max_workers=len(pending)) as executor:
                futures = [
                    executor.submit(
                        self._execute_judge,
                        answer=answer,
                        config=config,
                        judge_model=judge_model,
                        stored_role=stored_role,
                        trigger_reason="primary_panel",
                        terminal_progress=False,
                    )
                    for judge_model, stored_role in pending
                ]
                return [future.result() for future in futures]


def _arbiter_reason(config: RuntimeJudgeConfig, score_delta: int) -> str | None:
    if config.always_run_arbiter:
        return "forced_by_cli_or_env"
    if score_delta >= config.arbitration_min_delta:
        return "score_delta"
    return None
