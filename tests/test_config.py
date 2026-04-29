from __future__ import annotations

import pytest

from atividade_2.config import ConfigurationError, load_settings, resolve_runtime_config


BASE_ENV = {
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/app_dev",
    "JUDGE_PROVIDER": "remote_http",
    "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
    "REMOTE_JUDGE_API_KEY": "test-key",
    "JUDGE_PANEL_MODE": "2plus1",
    "REMOTE_JUDGE_MODEL": "m-prometheus-14b",
    "REMOTE_PRIMARY_JUDGE_PANEL": "gpt-oss-120b,llama-3.3-70b-instruct",
    "REMOTE_ARBITER_JUDGE_MODEL": "m-prometheus-14b",
    "JUDGE_EXECUTION_STRATEGY": "sequential",
}


def test_settings_load_default_models_from_env() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)

    assert settings.remote_judge_default_model == "m-prometheus-14b"
    assert settings.remote_primary_judge_panel == (
        "gpt-oss-120b",
        "llama-3.3-70b-instruct",
    )
    assert settings.remote_arbiter_judge_model == "m-prometheus-14b"
    assert settings.judge_execution_strategy == "sequential"


def test_judge_model_cli_override_forces_single_mode() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(settings, judge_model="custom/provider")

    assert config.panel_mode == "single"
    assert config.single_judge is not None
    assert config.single_judge.provider_model == "custom/provider"


def test_primary_panel_cli_override_wins() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(
        settings,
        panel_mode="primary_only",
        primary_judge_panel="model-a,model-b",
    )

    assert [model.provider_model for model in config.primary_panel] == ["model-a", "model-b"]


def test_arbiter_cli_override_wins() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(
        settings,
        panel_mode="2plus1",
        arbiter_judge_model="custom-arbiter",
    )

    assert config.arbiter is not None
    assert config.arbiter.provider_model == "custom-arbiter"


def test_remote_http_requires_base_url() -> None:
    env = dict(BASE_ENV)
    env.pop("REMOTE_JUDGE_BASE_URL")
    settings = load_settings(dotenv_path=None, env=env)

    with pytest.raises(ConfigurationError, match="REMOTE_JUDGE_BASE_URL"):
        resolve_runtime_config(settings, panel_mode="single")


def test_execution_strategy_cli_override_wins() -> None:
    settings = load_settings(dotenv_path=None, env=BASE_ENV)
    config = resolve_runtime_config(
        settings,
        panel_mode="primary_only",
        execution_strategy="parallel",
    )

    assert config.execution_strategy == "parallel"


def test_invalid_execution_strategy_fails() -> None:
    env = dict(BASE_ENV)
    env["JUDGE_EXECUTION_STRATEGY"] = "batch"

    with pytest.raises(ConfigurationError, match="JUDGE_EXECUTION_STRATEGY"):
        load_settings(dotenv_path=None, env=env)
