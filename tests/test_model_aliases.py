from __future__ import annotations

from atividade_2.model_aliases import resolve_judge_model


def test_required_judge_aliases_resolve() -> None:
    assert resolve_judge_model("gpt-oss-120b").provider_model == "openai/gpt-oss-120b"
    assert (
        resolve_judge_model("llama-3.3-70b-instruct").provider_model
        == "meta-llama/Llama-3.3-70B-Instruct"
    )
    assert resolve_judge_model("m-prometheus-14b").provider_model == "Unbabel/M-Prometheus-14B"


def test_unknown_model_passes_through() -> None:
    assert resolve_judge_model("provider/custom-model").provider_model == "provider/custom-model"
