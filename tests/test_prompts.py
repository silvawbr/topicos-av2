from __future__ import annotations

from atividade_2.contracts import CandidateAnswerContext
from atividade_2.prompts import build_judge_prompt


def test_prompt_contains_required_legal_context() -> None:
    prompt = build_judge_prompt(
        CandidateAnswerContext(
            answer_id=1,
            question_id=10,
            dataset_name="OAB_Bench",
            question_text="Elabore a peça cabível.",
            reference_answer="Rubrica jurídica",
            candidate_answer="A, porque a regra aplicável exige isso.",
            candidate_model="jurema-7b",
        )
    )

    assert "Elabore a peça cabível." in prompt
    assert "A, porque a regra aplicável exige isso." in prompt
    assert "Gabarito (Resposta Ouro)" in prompt
    assert "Retorne somente um objeto JSON bruto" in prompt
    assert "Não use markdown" in prompt
    assert "densidade de informação correta" in prompt


def test_j2_prompt_uses_binary_multiple_choice_scale() -> None:
    prompt = build_judge_prompt(
        CandidateAnswerContext(
            answer_id=1,
            question_id=101,
            dataset_name="OAB_Exames",
            question_text="Qual alternativa correta?",
            reference_answer="A",
            candidate_answer="Portanto, a opção correta é A.",
            candidate_model="jurema-7b",
        )
    )

    assert "múltipla escolha" in prompt
    assert "Use somente as notas 1 ou 5" in prompt
    assert "priorize a alternativa final explicitamente marcada" in prompt
    assert "não penalize ausência de fundamentação" in prompt
    assert "não premie fundamentação longa" in prompt
    assert "2 =" not in prompt
    assert "3 =" not in prompt
    assert "4 =" not in prompt


def test_j1_prompt_keeps_ordinal_open_ended_scale() -> None:
    prompt = build_judge_prompt(
        CandidateAnswerContext(
            answer_id=1,
            question_id=10,
            dataset_name="OAB_Bench",
            question_text="Elabore a peça cabível.",
            reference_answer="Rubrica jurídica",
            candidate_answer="Texto da peça.",
            candidate_model="jurema-7b",
        )
    )

    assert "Rubrica de avaliação (1 a 5)" in prompt
    assert "Nota 2: Conclusão correta" in prompt
    assert "Nota 5: Resposta excepcional" in prompt
    assert "Use somente as notas 1 ou 5" not in prompt
