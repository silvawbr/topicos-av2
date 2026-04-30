from __future__ import annotations

from atividade_2.config import load_settings
from atividade_2.run_judge_service import RunJudgeRequest, RunJudgeService


BASE_ENV = {
    "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
    "REMOTE_JUDGE_API_KEY": "test-key",
    "REMOTE_JUDGE_MODEL": "gpt-oss-120b",
    "REMOTE_SECONDARY_JUDGE_MODEL": "llama-3.3-70b-instruct",
    "REMOTE_ARBITER_JUDGE_MODEL": "m-prometheus-14b",
}


def test_dry_run_does_not_connect_to_database(tmp_path) -> None:
    def fail_connect(database_url: str):
        raise AssertionError("dry-run must not connect to PostgreSQL")

    service = RunJudgeService(
        settings_loader=lambda: load_settings(dotenv_path=None, env=BASE_ENV),
        connect_func=fail_connect,
    )

    result = service.run(
        RunJudgeRequest(
            panel_mode="single",
            judge_model="m-prometheus-14b",
            batch_size=1,
            dry_run=True,
            audit_log=str(tmp_path / "dry-run.log"),
            no_audit_animation=True,
        )
    )

    assert result.dry_run is True
    assert result.summary is None
    assert "Judge mode: single" in result.execution_summary
    assert "test-key" not in result.execution_summary
    assert "--dry-run" in result.command_preview


def test_describe_config_is_secret_safe() -> None:
    service = RunJudgeService(settings_loader=lambda: load_settings(dotenv_path=None, env=BASE_ENV))

    config = service.describe_config()

    assert config["endpoints"]["JUDGE"] == {"host": "example.invalid", "has_api_key": True}
    assert "test-key" not in str(config)


def test_invalid_configuration_is_reported_in_config_description() -> None:
    service = RunJudgeService(settings_loader=lambda: load_settings(dotenv_path=None, env={}))

    config = service.describe_config()

    assert "configuration_error" in config
    assert "REMOTE_JUDGE_BASE_URL is required" in config["configuration_error"]


def test_resolve_applies_web_endpoint_and_advanced_overrides() -> None:
    service = RunJudgeService(settings_loader=lambda: load_settings(dotenv_path=None, env=BASE_ENV))

    resolved = service.resolve(
        RunJudgeRequest(
            panel_mode="2plus1",
            remote_judge_base_url="https://judge1.example.invalid/v1",
            remote_judge_api_key="key-1",
            remote_secondary_judge_base_url="https://judge2.example.invalid/v1",
            remote_secondary_judge_api_key="key-2",
            remote_arbiter_judge_base_url="https://arbiter.example.invalid/v1",
            remote_arbiter_judge_api_key="key-3",
            judge_arbitration_min_delta=1,
            remote_judge_timeout_seconds=240,
            remote_judge_temperature=0.0,
            remote_judge_max_tokens=4000,
            remote_judge_top_p=1.0,
            remote_judge_openai_compatible=True,
            judge_save_raw_response=False,
        )
    )

    settings = resolved.runtime_config.settings
    assert settings.remote_judge_base_url == "https://judge1.example.invalid/v1"
    assert settings.remote_judge_api_key == "key-1"
    assert settings.remote_judge_endpoints["SECONDARY_JUDGE"].base_url == "https://judge2.example.invalid/v1"
    assert settings.remote_judge_endpoints["ARBITER"].api_key == "key-3"
    assert resolved.runtime_config.arbitration_min_delta == 1
    assert settings.remote_judge_timeout_seconds == 240
    assert settings.remote_judge_max_tokens == 4000
    assert settings.judge_save_raw_response is False
    assert "key-" not in resolved.command_preview


def test_endpoint_override_requires_url_and_key_together() -> None:
    service = RunJudgeService(settings_loader=lambda: load_settings(dotenv_path=None, env=BASE_ENV))

    try:
        service.resolve(
            RunJudgeRequest(
                panel_mode="single",
                remote_secondary_judge_base_url="https://judge2.example.invalid/v1",
            )
        )
    except ValueError as error:
        assert "Both URL and token/key are required" in str(error)
    else:
        raise AssertionError("incomplete endpoint override should fail")
