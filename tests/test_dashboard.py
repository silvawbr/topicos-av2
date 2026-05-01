from __future__ import annotations

from atividade_2.dashboard import DashboardFilters, build_dashboard_payload, spearman


def _row(
    *,
    evaluation_id: int,
    answer_id: int,
    dataset: str,
    candidate_answer: str,
    reference_answer: str,
    score: int,
    role: str = "principal",
    candidate_model: str = "modelo-a",
    judge_model: str = "juiz-a",
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "answer_id": answer_id,
        "question_id": answer_id + 100,
        "dataset": dataset,
        "dataset_name": "OAB_Exames" if dataset == "J2" else "OAB_Bench",
        "candidate_model": candidate_model,
        "judge_model": judge_model,
        "role": role,
        "status": "success",
        "score": score,
        "evaluated_at": "2026-04-30T10:00:00",
        "candidate_answer": candidate_answer,
        "reference_answer": reference_answer,
        "metadata": {},
        "trigger_reason": "2plus1:primary_panel",
    }


def test_spearman_uses_average_ranks_for_ties() -> None:
    result = spearman([5, 1, 5, 1], [5, 1, 5, 1])

    assert result["available"] is True
    assert result["value"] == 1.0
    assert result["sample_size"] == 4


def test_dashboard_calculates_j2_primary_spearman_from_answer_key() -> None:
    rows = [
        _row(evaluation_id=1, answer_id=1, dataset="J2", candidate_answer="B", reference_answer="B", score=5),
        _row(evaluation_id=2, answer_id=2, dataset="J2", candidate_answer="C", reference_answer="B", score=1),
        _row(evaluation_id=3, answer_id=3, dataset="J2", candidate_answer="D", reference_answer="D", score=5),
        _row(evaluation_id=4, answer_id=4, dataset="J2", candidate_answer="A", reference_answer="D", score=1),
    ]

    payload = build_dashboard_payload(rows, expected_answers=4, filters=DashboardFilters(dataset="J2"))

    spearman_card = payload["cards"]["spearman_reference"]
    assert spearman_card["available"] is True
    assert spearman_card["value"] == 1.0
    assert payload["cards"]["coverage"] == {"evaluated": 4, "expected": 4, "percent": 100.0}


def test_dashboard_marks_j1_primary_spearman_unavailable_without_reference_score() -> None:
    rows = [
        _row(evaluation_id=1, answer_id=1, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=4),
        _row(evaluation_id=2, answer_id=2, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=2),
    ]

    payload = build_dashboard_payload(rows, expected_answers=2, filters=DashboardFilters(dataset="J1"))

    spearman_card = payload["cards"]["spearman_reference"]
    assert spearman_card["available"] is False
    assert spearman_card["value"] is None
    assert "J1" in spearman_card["note"]


def test_dashboard_reports_judge_arbiter_as_complementary_consistency() -> None:
    rows = [
        _row(evaluation_id=1, answer_id=1, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=2),
        _row(
            evaluation_id=2,
            answer_id=1,
            dataset="J1",
            candidate_answer="texto",
            reference_answer="rubrica",
            score=2,
            role="arbitro",
            judge_model="arbitro",
        ),
        _row(evaluation_id=3, answer_id=2, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=5),
        _row(
            evaluation_id=4,
            answer_id=2,
            dataset="J1",
            candidate_answer="texto",
            reference_answer="rubrica",
            score=5,
            role="arbitro",
            judge_model="arbitro",
        ),
    ]

    payload = build_dashboard_payload(rows, expected_answers=2, filters=DashboardFilters(dataset="J1"))

    assert payload["cards"]["spearman_reference"]["available"] is False
    consistency = payload["cards"]["judge_arbiter_consistency"]
    assert consistency["available"] is True
    assert consistency["value"] == 1.0
    assert "Meta-avaliação" in consistency["note"]


def test_dashboard_reports_score_distribution_by_candidate_model() -> None:
    rows = [
        _row(evaluation_id=1, answer_id=1, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=1, candidate_model="modelo-a"),
        _row(evaluation_id=2, answer_id=2, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=5, candidate_model="modelo-a"),
        _row(evaluation_id=3, answer_id=3, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=4, candidate_model="modelo-a"),
        _row(evaluation_id=4, answer_id=4, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=3, candidate_model="modelo-b"),
        _row(evaluation_id=5, answer_id=5, dataset="J1", candidate_answer="texto", reference_answer="rubrica", score=3, candidate_model="modelo-b"),
    ]

    payload = build_dashboard_payload(rows, expected_answers=5, filters=DashboardFilters(dataset="J1"))

    assert payload["charts"]["score_distribution_by_model"] == [
        {"label": "modelo-a", "total": 3, "average": 3.33, "scores": {"1": 1, "2": 0, "3": 0, "4": 1, "5": 1}},
        {"label": "modelo-b", "total": 2, "average": 3, "scores": {"1": 0, "2": 0, "3": 2, "4": 0, "5": 0}},
    ]
