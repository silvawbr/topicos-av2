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


def test_parser_rejects_out_of_range_score() -> None:
    with pytest.raises(JudgeParseError, match="between 1 and 5"):
        parse_judge_output('{"score": 6, "rationale": "fora da escala"}')


def test_parser_rejects_unparseable_response() -> None:
    with pytest.raises(JudgeParseError):
        parse_judge_output("nota cinco, resposta boa")
