from __future__ import annotations

from atividade_2.contracts import ModelSpec
from atividade_2.repositories import JudgeRepository


class RecordingCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, query, params=None) -> None:
        self.query = query
        self.params = list(params or [])

    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance


def test_pending_answer_selection_takes_a_batch_per_required_judge() -> None:
    connection = RecordingConnection()
    repository = JudgeRepository(connection)
    repository.ensure_judge_model = lambda model: 10 if model.requested == "judge-1" else 20  # type: ignore[method-assign]

    repository.select_pending_candidate_answers(
        dataset="J2",
        batch_size=2,
        required_evaluations=(
            (ModelSpec(requested="judge-1", provider_model="provider/judge-1"), "principal", "2plus1"),
            (ModelSpec(requested="judge-2", provider_model="provider/judge-2"), "controle", "2plus1"),
        ),
    )

    query = connection.cursor_instance.query
    assert "ROW_NUMBER() OVER" in query
    assert "PARTITION BY" in query
    assert "required.id_modelo_juiz" in query
    assert "required.papel_juiz" in query
    assert "WHERE required_rank <= %s" in query
    assert connection.cursor_instance.params[-1] == 2
