from __future__ import annotations

from atividade_2.contracts import CandidateAnswerContext
from atividade_2.prompts import build_judge_prompt


def test_prompt_contains_required_legal_context() -> None:
    prompt = build_judge_prompt(
        CandidateAnswerContext(
            answer_id=1,
            question_id=10,
            dataset_name="OAB_Exames",
            question_text="Qual alternativa correta?",
            reference_answer="A",
            candidate_answer="A, porque a regra aplicável exige isso.",
            candidate_model="jurema-7b",
        )
    )

    assert "Qual alternativa correta?" in prompt
    assert "A, porque a regra aplicável exige isso." in prompt
    assert "Resposta de referência" in prompt
    assert "Retorne somente JSON válido" in prompt
    assert "não recompense verbosidade" in prompt
