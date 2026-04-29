"""Central judge model alias resolution."""

from __future__ import annotations

from .contracts import ModelSpec

JUDGE_MODEL_ALIASES: dict[str, str] = {
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "llama-3.3-70b-instruct": "meta-llama/Llama-3.3-70B-Instruct",
    "m-prometheus-14b": "Unbabel/M-Prometheus-14B",
}


def resolve_judge_model(value: str) -> ModelSpec:
    """Resolve a judge alias, passing full provider ids through unchanged."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("Judge model cannot be empty.")
    return ModelSpec(
        requested=normalized,
        provider_model=JUDGE_MODEL_ALIASES.get(normalized, normalized),
    )


def format_model_mapping(model: ModelSpec) -> str:
    """Format a model mapping for safe CLI output."""
    if model.requested == model.provider_model:
        return f"- {model.provider_model}"
    return f"- {model.requested} -> {model.provider_model}"
