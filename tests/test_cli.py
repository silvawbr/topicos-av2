"""Tests for the command-line interface baseline."""

from __future__ import annotations

import pytest

from atividade_2 import cli


def test_cli_help_exits_successfully() -> None:
    """The CLI help command should be available through argparse."""
    with pytest.raises(SystemExit) as exit_error:
        cli.main(["--help"])

    assert exit_error.value.code == 0


def test_run_judge_help_exits_successfully() -> None:
    """The judge command should expose runtime options."""
    with pytest.raises(SystemExit) as exit_error:
        cli.main(["run-judge", "--help"])

    assert exit_error.value.code == 0


def test_run_judge_dry_run_prints_single_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    """Dry-run should resolve config without DB or HTTP calls."""
    monkeypatch.setenv("REMOTE_JUDGE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("REMOTE_JUDGE_API_KEY", "test-key")
    monkeypatch.setenv("REMOTE_JUDGE_MODEL", "m-prometheus-14b")
    audit_path = tmp_path / "audit.log"

    exit_code = cli.main(
        [
            "run-judge",
            "--panel-mode",
            "single",
            "--dataset",
            "J2",
            "--limit",
            "1",
            "--dry-run",
            "--audit-log",
            str(audit_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Judge mode: single" in output
    assert "m-prometheus-14b -> Unbabel/M-Prometheus-14B" in output
    assert f"Audit log: {audit_path}" in output
    assert "test-key" not in output
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "START Loading configuration" in audit_text
    assert "execution_summary" in audit_text
    assert "dry_run_finished" in audit_text
