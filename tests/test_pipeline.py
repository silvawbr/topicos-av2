from __future__ import annotations

from contextlib import contextmanager

from atividade_2.config import load_settings, resolve_runtime_config
from atividade_2.contracts import BatchProgress, CandidateAnswerContext, EvaluationProgress, JudgeRawResponse
from atividade_2.pipeline import JudgePipeline
from atividade_2.repositories import InMemoryJudgeRepository


BASE_ENV = {
    "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
    "REMOTE_JUDGE_API_KEY": "test-key",
    "REMOTE_JUDGE_MODEL": "gpt-oss-120b",
    "REMOTE_SECONDARY_JUDGE_MODEL": "llama-3.3-70b-instruct",
    "REMOTE_ARBITER_JUDGE_MODEL": "m-prometheus-14b",
}


class FakeJudgeClient:
    def __init__(self, scores: dict[str, int]) -> None:
        self.scores = scores
        self.calls: list[str] = []
        self.endpoint_keys: list[str | None] = []

    def judge(
        self,
        prompt: str,
        model: str,
        *,
        requested_model: str | None = None,
        endpoint_key: str | None = None,
    ) -> JudgeRawResponse:
        self.calls.append(model)
        self.endpoint_keys.append(endpoint_key)
        score = self.scores[model]
        return JudgeRawResponse(
            text=f'{{"score": {score}, "rationale": "nota {score}"}}',
            provider="fake",
            model=model,
            latency_ms=1,
        )


class RecordingAudit:
    def __init__(self) -> None:
        self.terminal_messages: list[str] = []
        self.file_events: list[tuple[str, str | None]] = []
        self.events: list[tuple[str, str | None]] = []

    def terminal_event(self, message: str) -> None:
        self.terminal_messages.append(message)

    def file_event(self, message: str, detail: str | None = None) -> None:
        self.file_events.append((message, detail))

    def event(self, event) -> None:
        self.events.append((event.message, event.detail))

    @contextmanager
    def step(self, message: str, *, detail: str | None = None, terminal: bool = True):
        yield


def answer() -> CandidateAnswerContext:
    return CandidateAnswerContext(
        answer_id=1,
        question_id=1,
        dataset_name="OAB_Exames",
        question_text="Enunciado",
        reference_answer="A",
        candidate_answer="A",
        candidate_model="candidate",
    )


def answer_with_id(answer_id: int) -> CandidateAnswerContext:
    base_answer = answer()
    return CandidateAnswerContext(
        answer_id=answer_id,
        question_id=base_answer.question_id,
        dataset_name=base_answer.dataset_name,
        question_text=base_answer.question_text,
        reference_answer=base_answer.reference_answer,
        candidate_answer=base_answer.candidate_answer,
        candidate_model=base_answer.candidate_model,
    )


def test_single_mode_runs_one_judge() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"openai/gpt-oss-120b": 5})

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 1
    assert len(repo.records) == 1
    assert repo.records[0].stored_role == "principal"
    assert client.endpoint_keys == ["JUDGE"]


def test_pipeline_reports_batch_progress_after_each_answer() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"openai/gpt-oss-120b": 5})
    audit = RecordingAudit()
    progress_events: list[BatchProgress] = []

    JudgePipeline(repo, client, audit=audit, progress_callback=progress_events.append).run(
        [answer_with_id(1), answer_with_id(2)],
        config,
    )

    assert "Batch progress: 1/2 answers (50%) | executed=1 skipped=0 arbiters=0" in audit.terminal_messages
    assert "Batch progress: 2/2 answers (100%) | executed=2 skipped=0 arbiters=0" in audit.terminal_messages
    assert (
        "batch_progress",
        "current=2 total=2 percent=100 executed=2 skipped=0 arbiters=0",
    ) in audit.events
    assert progress_events == [
        BatchProgress(
            current=1,
            total=2,
            percent=50,
            executed_evaluations=1,
            skipped_evaluations=0,
            arbiter_evaluations=0,
        ),
        BatchProgress(
            current=2,
            total=2,
            percent=100,
            executed_evaluations=2,
            skipped_evaluations=0,
            arbiter_evaluations=0,
        ),
    ]


def test_pipeline_stops_between_answers_without_discarding_completed_records() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"openai/gpt-oss-120b": 5})
    audit = RecordingAudit()
    progress_events: list[BatchProgress] = []
    stop_after_first = False

    def record_progress(progress: BatchProgress) -> None:
        nonlocal stop_after_first
        progress_events.append(progress)
        stop_after_first = True

    summary = JudgePipeline(
        repo,
        client,
        audit=audit,
        progress_callback=record_progress,
        should_stop=lambda: stop_after_first,
    ).run([answer_with_id(1), answer_with_id(2)], config)

    assert summary.executed_evaluations == 1
    assert [record.answer_id for record in repo.records] == [1]
    assert client.calls == ["openai/gpt-oss-120b"]
    assert progress_events == [
        BatchProgress(
            current=1,
            total=2,
            percent=50,
            executed_evaluations=1,
            skipped_evaluations=0,
            arbiter_evaluations=0,
        )
    ]
    assert (
        "pipeline_cancelled",
        "current=1 total=2 executed=1 skipped=0 arbiters=0",
    ) in audit.events


def test_pipeline_reports_evaluation_rows_for_web_table() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"openai/gpt-oss-120b": 5})
    evaluation_events: list[EvaluationProgress] = []

    JudgePipeline(repo, client, evaluation_callback=evaluation_events.append).run([answer()], config)

    assert [event.status for event in evaluation_events] == ["running", "success"]
    success = evaluation_events[-1]
    assert success.dataset == "OAB_Exames"
    assert success.question_id == 1
    assert success.candidate_model == "candidate"
    assert success.judge_model == "openai/gpt-oss-120b"
    assert success.role == "principal"
    assert success.score == 5
    assert success.latency_ms == 1
    assert success.prompt
    assert success.raw_response == '{"score": 5, "rationale": "nota 5"}'
    assert success.rationale == "nota 5"


def test_pipeline_reports_complete_progress_for_empty_batch() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    audit = RecordingAudit()
    progress_events: list[BatchProgress] = []

    summary = JudgePipeline(
        InMemoryJudgeRepository(),
        FakeJudgeClient({"openai/gpt-oss-120b": 5}),
        audit=audit,
        progress_callback=progress_events.append,
    ).run([], config)

    assert summary.selected_answers == 0
    assert progress_events == [
        BatchProgress(
            current=0,
            total=0,
            percent=100,
            executed_evaluations=0,
            skipped_evaluations=0,
            arbiter_evaluations=0,
        )
    ]


def test_pipeline_does_not_fail_when_progress_callback_fails() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    audit = RecordingAudit()

    def fail_progress_callback(progress: BatchProgress) -> None:
        raise RuntimeError("progress sink unavailable")

    summary = JudgePipeline(
        InMemoryJudgeRepository(),
        FakeJudgeClient({"openai/gpt-oss-120b": 5}),
        audit=audit,
        progress_callback=fail_progress_callback,
    ).run([answer()], config)

    assert summary.executed_evaluations == 1
    assert (
        "batch_progress_callback_failed",
        "error=progress sink unavailable",
    ) in audit.events


def test_primary_only_runs_panel_without_arbiter() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="primary_only")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient(
        {
            "openai/gpt-oss-120b": 5,
            "meta-llama/Llama-3.3-70B-Instruct": 1,
            "Unbabel/M-Prometheus-14B": 4,
        }
    )

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 2
    assert summary.arbiter_evaluations == 0
    assert client.calls == ["openai/gpt-oss-120b", "meta-llama/Llama-3.3-70B-Instruct"]
    assert client.endpoint_keys == ["JUDGE", "SECONDARY_JUDGE"]


def test_2plus1_skips_arbiter_below_threshold() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="2plus1")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient(
        {
            "openai/gpt-oss-120b": 4,
            "meta-llama/Llama-3.3-70B-Instruct": 3,
            "Unbabel/M-Prometheus-14B": 1,
        }
    )

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 2
    assert summary.arbiter_evaluations == 0


def test_2plus1_runs_arbiter_at_threshold() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="2plus1")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient(
        {
            "openai/gpt-oss-120b": 5,
            "meta-llama/Llama-3.3-70B-Instruct": 3,
            "Unbabel/M-Prometheus-14B": 4,
        }
    )

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 3
    assert summary.arbiter_evaluations == 1
    assert client.endpoint_keys == ["JUDGE", "SECONDARY_JUDGE", "ARBITER"]


def test_always_run_arbiter_forces_execution() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="2plus1", always_run_arbiter=True)
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient(
        {
            "openai/gpt-oss-120b": 4,
            "meta-llama/Llama-3.3-70B-Instruct": 4,
            "Unbabel/M-Prometheus-14B": 4,
        }
    )

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 3
    assert summary.arbiter_evaluations == 1


def test_duplicate_evaluation_is_skipped() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"openai/gpt-oss-120b": 5})
    pipeline = JudgePipeline(repo, client)

    first = pipeline.run([answer()], config)
    second = pipeline.run([answer()], config)

    assert first.executed_evaluations == 1
    assert second.executed_evaluations == 0
    assert second.skipped_evaluations == 1
    assert len(repo.records) == 1


def test_primary_only_supports_parallel_strategy() -> None:
    env = dict(BASE_ENV)
    env["JUDGE_EXECUTION_STRATEGY"] = "parallel"
    settings = load_settings(dotenv_path=None, env=env)
    config = resolve_runtime_config(settings, panel_mode="primary_only")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient(
        {
            "openai/gpt-oss-120b": 5,
            "meta-llama/Llama-3.3-70B-Instruct": 4,
        }
    )

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert config.execution_strategy == "parallel"
    assert summary.executed_evaluations == 2
    assert sorted(client.calls) == [
        "meta-llama/Llama-3.3-70B-Instruct",
        "openai/gpt-oss-120b",
    ]
