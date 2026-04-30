"""PostgreSQL dump generation for Web UI audit exports."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_settings

DUMP_FILENAME_PATTERN = re.compile(r"^atividade_2_\d{8}_\d{6}\.sql$")


@dataclass(frozen=True)
class DatabaseDumpResult:
    """Metadata for a generated database dump."""

    filename: str
    path: str
    size_bytes: int
    created_at: str
    download_url: str


class DatabaseDumpService:
    """Generate complete plain SQL PostgreSQL dumps."""

    def __init__(
        self,
        *,
        output_dir: Path | str = Path("outputs") / "backup",
        settings_loader: Callable[[], Any] = load_settings,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.output_dir = Path(output_dir)
        self._settings_loader = settings_loader
        self._now = now

    def create_dump(self) -> DatabaseDumpResult:
        """Run pg_dump and return the generated artifact metadata."""
        pg_dump = shutil.which("pg_dump")
        if pg_dump is None:
            raise RuntimeError("pg_dump não encontrado no ambiente da Web UI.")

        settings = self._settings_loader()
        created_at = self._now()
        filename = f"atividade_2_{created_at:%Y%m%d_%H%M%S}.sql"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = (self.output_dir / filename).resolve()
        command = [pg_dump, settings.database_url, "--file", str(output_path)]
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as error:
            output_path.unlink(missing_ok=True)
            raise RuntimeError("pg_dump excedeu o tempo limite de 300 segundos.") from error

        if completed.returncode != 0:
            output_path.unlink(missing_ok=True)
            detail = _redact(completed.stderr or completed.stdout or "pg_dump falhou.", settings.database_url)
            raise RuntimeError(f"Falha ao gerar dump do banco: {detail}") from None

        return DatabaseDumpResult(
            filename=filename,
            path=str(output_path),
            size_bytes=output_path.stat().st_size,
            created_at=created_at.isoformat(),
            download_url=f"/api/database-dumps/{filename}",
        )


def resolve_dump_path(output_dir: Path | str, filename: str) -> Path:
    """Resolve a dump filename inside the configured output directory."""
    if not DUMP_FILENAME_PATTERN.fullmatch(filename):
        raise ValueError("Nome de dump inválido.")
    root = Path(output_dir).resolve()
    path = (root / filename).resolve()
    if path.parent != root:
        raise ValueError("Nome de dump inválido.")
    return path


def _redact(message: str, secret: str) -> str:
    redacted = message.replace(secret, "<redacted>")
    redacted = re.sub(r"postgresql://([^:\s]+):([^@\s]+)@", r"postgresql://\1:<redacted>@", redacted)
    return redacted.strip()
