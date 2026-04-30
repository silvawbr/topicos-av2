"""PostgreSQL repository for judge pipeline reads and writes."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from .contracts import CandidateAnswerContext, EligibilitySummary, EvaluationRecord, ModelSpec, StoredJudgeRole

DATASET_ALIASES = {
    "J1": "OAB_Bench",
    "J2": "OAB_Exames",
}


class JudgeRepositoryProtocol(Protocol):
    """Repository operations required by the pipeline."""

    def evaluation_exists(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> bool:
        """Return whether this answer/model/role/mode was already persisted."""

    def existing_score(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> int | None:
        """Return a persisted score if available."""

    def persist_evaluation(self, record: EvaluationRecord) -> None:
        """Persist a successful evaluation."""

    def select_pending_candidate_answers(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> list[CandidateAnswerContext]:
        """Select AV1 answers still missing at least one required successful evaluation."""

    def summarize_eligibility(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> EligibilitySummary:
        """Count answer-level eligibility before selecting the execution batch."""


class JudgeRepository:
    """SQL repository using the existing AV2 PostgreSQL schema."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def ensure_schema(self) -> None:
        """Add optional multi-judge metadata columns when the restored schema lacks them."""
        with self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute("ALTER TABLE avaliacoes_juiz ADD COLUMN IF NOT EXISTS papel_juiz VARCHAR(20);")
                cursor.execute("ALTER TABLE avaliacoes_juiz ADD COLUMN IF NOT EXISTS rodada_julgamento VARCHAR(30);")
                cursor.execute("ALTER TABLE avaliacoes_juiz ADD COLUMN IF NOT EXISTS motivo_acionamento TEXT;")
                cursor.execute(
                    "ALTER TABLE avaliacoes_juiz "
                    "ADD COLUMN IF NOT EXISTS status_avaliacao VARCHAR(20) DEFAULT 'success';"
                )

    def select_candidate_answers(self, *, dataset: str, limit: int | None) -> list[CandidateAnswerContext]:
        """Select AV1 answers with question/reference context."""
        dataset_name = DATASET_ALIASES.get(dataset.upper(), dataset)
        params: list[Any] = [dataset_name]
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT %s"
            params.append(limit)

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    r.id_resposta,
                    p.id_pergunta,
                    d.nome_dataset,
                    p.enunciado,
                    p.resposta_ouro,
                    r.texto_resposta,
                    m.nome_modelo,
                    COALESCE(p.metadados, '{{}}'::jsonb)
                FROM respostas_atividade_1 r
                JOIN perguntas p ON p.id_pergunta = r.id_pergunta
                JOIN datasets d ON d.id_dataset = p.id_dataset
                JOIN modelos m ON m.id_modelo = r.id_modelo
                WHERE d.nome_dataset = %s
                ORDER BY r.id_resposta
                {limit_clause};
                """,
                params,
            )
            rows = cursor.fetchall()

        return [
            CandidateAnswerContext(
                answer_id=row[0],
                question_id=row[1],
                dataset_name=row[2],
                question_text=row[3],
                reference_answer=row[4],
                candidate_answer=row[5],
                candidate_model=row[6],
                metadata=_normalize_metadata(row[7]),
            )
            for row in rows
        ]

    def select_pending_candidate_answers(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> list[CandidateAnswerContext]:
        """Select candidate answers with at least one missing required evaluation."""
        required = tuple(required_evaluations)
        if not required:
            return []
        model_ids = [self.ensure_judge_model(model) for model, _, _ in required]
        values_sql = ", ".join(["(%s, %s, %s)"] * len(required))
        required_params: list[Any] = []
        for model_id, (_, role, panel_mode) in zip(model_ids, required, strict=True):
            required_params.extend([model_id, role, f"{panel_mode}:%"])

        dataset_name = DATASET_ALIASES.get(dataset.upper(), dataset)
        params: list[Any] = [*required_params, dataset_name, batch_size]
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH required_evaluations(id_modelo_juiz, papel_juiz, motivo_pattern) AS (
                    VALUES {values_sql}
                )
                SELECT
                    r.id_resposta,
                    p.id_pergunta,
                    d.nome_dataset,
                    p.enunciado,
                    p.resposta_ouro,
                    r.texto_resposta,
                    m.nome_modelo,
                    COALESCE(p.metadados, '{{}}'::jsonb)
                FROM respostas_atividade_1 r
                JOIN perguntas p ON p.id_pergunta = r.id_pergunta
                JOIN datasets d ON d.id_dataset = p.id_dataset
                JOIN modelos m ON m.id_modelo = r.id_modelo
                WHERE d.nome_dataset = %s
                  AND EXISTS (
                      SELECT 1
                      FROM required_evaluations required
                      WHERE NOT EXISTS (
                          SELECT 1
                          FROM avaliacoes_juiz a
                          WHERE a.id_resposta_ativa1 = r.id_resposta
                            AND a.id_modelo_juiz = required.id_modelo_juiz
                            AND COALESCE(a.papel_juiz, '') = required.papel_juiz
                            AND COALESCE(a.motivo_acionamento, '') LIKE required.motivo_pattern
                            AND COALESCE(a.status_avaliacao, 'success') = 'success'
                      )
                  )
                ORDER BY r.id_resposta
                LIMIT %s;
                """,
                params,
            )
            rows = cursor.fetchall()

        return [
            CandidateAnswerContext(
                answer_id=row[0],
                question_id=row[1],
                dataset_name=row[2],
                question_text=row[3],
                reference_answer=row[4],
                candidate_answer=row[5],
                candidate_model=row[6],
                metadata=_normalize_metadata(row[7]),
            )
            for row in rows
        ]

    def summarize_eligibility(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> EligibilitySummary:
        """Count missing, failed, successful, and next-batch answer totals."""
        required = tuple(required_evaluations)
        if not required:
            return EligibilitySummary(missing=0, failed=0, successful=0, batch_size=batch_size, will_process=0)

        model_ids = [self.ensure_judge_model(model) for model, _, _ in required]
        values_sql = ", ".join(["(%s, %s, %s)"] * len(required))
        required_params: list[Any] = []
        for model_id, (_, role, panel_mode) in zip(model_ids, required, strict=True):
            required_params.extend([model_id, role, f"{panel_mode}:%"])

        dataset_name = DATASET_ALIASES.get(dataset.upper(), dataset)
        params: list[Any] = [*required_params, dataset_name, len(required)]
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH required_evaluations(id_modelo_juiz, papel_juiz, motivo_pattern) AS (
                    VALUES {values_sql}
                ),
                answer_required_status AS (
                    SELECT
                        r.id_resposta,
                        required.id_modelo_juiz,
                        required.papel_juiz,
                        required.motivo_pattern,
                        BOOL_OR(
                            a.id_avaliacao IS NOT NULL
                            AND COALESCE(a.status_avaliacao, 'success') = 'success'
                        ) AS has_success,
                        BOOL_OR(
                            a.id_avaliacao IS NOT NULL
                            AND COALESCE(a.status_avaliacao, 'success') <> 'success'
                        ) AS has_failure
                    FROM respostas_atividade_1 r
                    JOIN perguntas p ON p.id_pergunta = r.id_pergunta
                    JOIN datasets d ON d.id_dataset = p.id_dataset
                    CROSS JOIN required_evaluations required
                    LEFT JOIN avaliacoes_juiz a
                      ON a.id_resposta_ativa1 = r.id_resposta
                     AND a.id_modelo_juiz = required.id_modelo_juiz
                     AND COALESCE(a.papel_juiz, '') = required.papel_juiz
                     AND COALESCE(a.motivo_acionamento, '') LIKE required.motivo_pattern
                    WHERE d.nome_dataset = %s
                    GROUP BY
                        r.id_resposta,
                        required.id_modelo_juiz,
                        required.papel_juiz,
                        required.motivo_pattern
                ),
                answer_status AS (
                    SELECT
                        id_resposta,
                        COUNT(*) FILTER (WHERE has_success) AS successful_required,
                        COUNT(*) FILTER (WHERE NOT has_success AND has_failure) AS failed_required
                    FROM answer_required_status
                    GROUP BY id_resposta
                )
                SELECT
                    COUNT(*) FILTER (WHERE successful_required = %s) AS successful,
                    COUNT(*) FILTER (WHERE successful_required < %s AND failed_required > 0) AS failed,
                    COUNT(*) FILTER (WHERE successful_required < %s AND failed_required = 0) AS missing
                FROM answer_status;
                """,
                [*params, len(required), len(required)],
            )
            row = cursor.fetchone()

        successful = int(row[0] or 0)
        failed = int(row[1] or 0)
        missing = int(row[2] or 0)
        return EligibilitySummary(
            missing=missing,
            failed=failed,
            successful=successful,
            batch_size=batch_size,
            will_process=min(batch_size, missing + failed),
        )

    def evaluation_exists(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> bool:
        return self.existing_score(answer_id, judge_model, stored_role, panel_mode) is not None

    def existing_score(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> int | None:
        model_id = self.ensure_judge_model(judge_model)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nota_atribuida
                FROM avaliacoes_juiz
                WHERE id_resposta_ativa1 = %s
                  AND id_modelo_juiz = %s
                  AND COALESCE(papel_juiz, '') = %s
                  AND COALESCE(motivo_acionamento, '') LIKE %s
                  AND COALESCE(status_avaliacao, 'success') = 'success'
                ORDER BY id_avaliacao DESC
                LIMIT 1;
                """,
                (answer_id, model_id, stored_role, f"{panel_mode}:%"),
            )
            row = cursor.fetchone()
        return int(row[0]) if row else None

    def persist_evaluation(self, record: EvaluationRecord) -> None:
        model_id = self.ensure_judge_model(record.judge_model)
        with self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO avaliacoes_juiz
                        (
                            id_resposta_ativa1,
                            id_modelo_juiz,
                            nota_atribuida,
                            prompt_juiz,
                            rubrica_utilizada,
                            chain_of_thought,
                            papel_juiz,
                            rodada_julgamento,
                            motivo_acionamento,
                            status_avaliacao
                        )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        record.answer_id,
                        model_id,
                        record.score,
                        record.prompt,
                        record.rubric,
                        record.rationale,
                        record.stored_role,
                        _round_for_role(record.stored_role),
                        f"{record.panel_mode}:{record.trigger_reason}",
                        "success",
                    ),
                )

    def ensure_judge_model(self, model: ModelSpec) -> int:
        """Return a judge model id, inserting it if necessary."""
        with self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id_modelo
                    FROM modelos
                    WHERE nome_modelo = %s
                      AND COALESCE(versao, '') = COALESCE(%s, '')
                      AND tipo_modelo IN ('juiz', 'ambos');
                    """,
                    (model.requested, model.provider_model),
                )
                row = cursor.fetchone()
                if row:
                    return int(row[0])
                cursor.execute(
                    """
                    INSERT INTO modelos (nome_modelo, versao, parametro_precisao, tipo_modelo)
                    VALUES (%s, %s, NULL, 'juiz')
                    RETURNING id_modelo;
                    """,
                    (model.requested, model.provider_model),
                )
                return int(cursor.fetchone()[0])


def _round_for_role(role: StoredJudgeRole) -> str:
    if role == "arbitro":
        return "arbitragem"
    return "padrao"


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class InMemoryJudgeRepository:
    """Small test repository for offline pipeline tests."""

    def __init__(self) -> None:
        self.records: list[EvaluationRecord] = []

    def evaluation_exists(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> bool:
        return self.existing_score(answer_id, judge_model, stored_role, panel_mode) is not None

    def existing_score(
        self,
        answer_id: int,
        judge_model: ModelSpec,
        stored_role: StoredJudgeRole,
        panel_mode: str,
    ) -> int | None:
        for record in reversed(self.records):
            if (
                record.answer_id == answer_id
                and record.judge_model.provider_model == judge_model.provider_model
                and record.stored_role == stored_role
                and record.panel_mode == panel_mode
            ):
                return record.score
        return None

    def persist_evaluation(self, record: EvaluationRecord) -> None:
        self.records.append(record)

    def extend(self, records: Iterable[EvaluationRecord]) -> None:
        self.records.extend(records)

    def select_pending_candidate_answers(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> list[CandidateAnswerContext]:
        return []

    def summarize_eligibility(
        self,
        *,
        dataset: str,
        batch_size: int,
        required_evaluations: Iterable[tuple[ModelSpec, StoredJudgeRole, str]],
    ) -> EligibilitySummary:
        return EligibilitySummary(missing=0, failed=0, successful=0, batch_size=batch_size, will_process=0)
