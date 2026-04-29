"""PostgreSQL repository for judge pipeline reads and writes."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from .contracts import CandidateAnswerContext, EvaluationRecord, ModelSpec, StoredJudgeRole

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
                            motivo_acionamento
                        )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
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
