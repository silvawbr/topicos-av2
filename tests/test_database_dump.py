from pathlib import Path
from types import SimpleNamespace

from atividade_2 import database_dump
from atividade_2.database_dump import DatabaseResetService


def test_restore_backup_adds_dashboard_compatibility_columns(monkeypatch, tmp_path) -> None:
    backup_file = tmp_path / "atividade_2_20260430_120000.sql"
    backup_file.write_text("SELECT 1;", encoding="utf-8")
    commands = []

    monkeypatch.setattr(database_dump.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, timeout_seconds, *, secret=None, expected_stdout=None):
        commands.append(command)

    monkeypatch.setattr(database_dump, "_run_command", fake_run_command)
    service = DatabaseResetService(
        settings_loader=lambda: SimpleNamespace(database_url="postgresql://postgres:postgres@localhost:5432/app_dev")
    )

    service.restore_backup(backup_file)

    alter_commands = [command for command in commands if "ALTER TABLE avaliacoes_juiz" in " ".join(command)]
    assert len(alter_commands) == 1
    alter_sql = " ".join(alter_commands[0])
    assert "ADD COLUMN IF NOT EXISTS papel_juiz" in alter_sql
    assert "ADD COLUMN IF NOT EXISTS rodada_julgamento" in alter_sql
    assert "ADD COLUMN IF NOT EXISTS motivo_acionamento" in alter_sql
    assert "ADD COLUMN IF NOT EXISTS status_avaliacao" in alter_sql
