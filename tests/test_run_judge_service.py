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
