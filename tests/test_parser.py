from __future__ import annotations

import pytest

from atividade_2.parser import JudgeParseError, parse_judge_output


def test_parser_extracts_valid_score_and_rationale() -> None:
    parsed = parse_judge_output(
        '{"nota": 4, "justificativa": "Resposta correta no essencial.", '
        '"requires_human_review": false}'
    )

    assert parsed.score == 4
    assert parsed.rationale == "Resposta correta no essencial."


def test_parser_extracts_json_code_fence() -> None:
    parsed = parse_judge_output(
        '```json\n{"nota": 4, "justificativa": "Resposta adequada."}\n```'
    )

    assert parsed.score == 4
    assert parsed.rationale == "Resposta adequada."


def test_parser_extracts_generic_code_fence() -> None:
    parsed = parse_judge_output(
        '```\n{"nota": 5, "justificativa": "Resposta completa."}\n```'
    )

    assert parsed.score == 5
    assert parsed.rationale == "Resposta completa."


def test_parser_extracts_json_with_text_before_and_after() -> None:
    parsed = parse_judge_output(
        'Segue a avaliação:\n{"nota": 3, "justificativa": "Parcial."}\nFim.'
    )

    assert parsed.score == 3
    assert parsed.rationale == "Parcial."


def test_parser_extracts_first_valid_json_object_after_incidental_braces() -> None:
    parsed = parse_judge_output(
        'Observação {não é json}. Resultado: {"nota": 4, "justificativa": "Ok."}'
    )

    assert parsed.score == 4
    assert parsed.rationale == "Ok."


def test_parser_rejects_out_of_range_score() -> None:
    with pytest.raises(JudgeParseError, match="between 1 and 5"):
        parse_judge_output('{"score": 6, "rationale": "fora da escala"}')


def test_parser_rejects_score_outside_allowed_scores() -> None:
    with pytest.raises(JudgeParseError, match="one of: 1, 5"):
        parse_judge_output('{"score": 3, "rationale": "parcial"}', allowed_scores={1, 5})


def test_parser_rejects_unparseable_response() -> None:
    with pytest.raises(JudgeParseError, match="does not contain a JSON object"):
        parse_judge_output("nota cinco, resposta boa")


def test_parser_rejects_missing_rationale() -> None:
    with pytest.raises(JudgeParseError, match="rationale/justificativa"):
        parse_judge_output('{"score": 4}')


def test_parser_rejects_empty_rationale() -> None:
    with pytest.raises(JudgeParseError, match="cannot be empty"):
        parse_judge_output('{"score": 4, "rationale": "   "}')
