from __future__ import annotations

from atividade_2.config import load_settings, resolve_runtime_config
from atividade_2.contracts import CandidateAnswerContext, JudgeRawResponse
from atividade_2.pipeline import JudgePipeline
from atividade_2.repositories import InMemoryJudgeRepository


BASE_ENV = {
    "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
    "REMOTE_JUDGE_API_KEY": "test-key",
    "REMOTE_JUDGE_MODEL": "m-prometheus-14b",
    "REMOTE_PRIMARY_JUDGE_PANEL": "gpt-oss-120b,llama-3.3-70b-instruct",
    "REMOTE_ARBITER_JUDGE_MODEL": "m-prometheus-14b",
}


class FakeJudgeClient:
    def __init__(self, scores: dict[str, int]) -> None:
        self.scores = scores
        self.calls: list[str] = []

    def judge(self, prompt: str, model: str) -> JudgeRawResponse:
        self.calls.append(model)
        score = self.scores[model]
        return JudgeRawResponse(
            text=f'{{"score": {score}, "rationale": "nota {score}"}}',
            provider="fake",
            model=model,
            latency_ms=1,
        )


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


def test_single_mode_runs_one_judge() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, panel_mode="single")
    repo = InMemoryJudgeRepository()
    client = FakeJudgeClient({"Unbabel/M-Prometheus-14B": 5})

    summary = JudgePipeline(repo, client).run([answer()], config)

    assert summary.executed_evaluations == 1
    assert len(repo.records) == 1
    assert repo.records[0].stored_role == "principal"


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
    client = FakeJudgeClient({"Unbabel/M-Prometheus-14B": 5})
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
