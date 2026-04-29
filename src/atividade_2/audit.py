"""Terminal and file audit logging for judge runs."""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import TextIO


@dataclass(frozen=True)
class AuditEvent:
    """Single audit event."""

    message: str
    detail: str | None = None


class AuditLogger:
    """Write concise terminal progress and detailed file audit events."""

    def __init__(
        self,
        *,
        file_path: Path,
        terminal: TextIO | None = None,
        animate: bool | None = None,
    ) -> None:
        self.file_path = file_path
        self.terminal = terminal or sys.stdout
        self.animate = self.terminal.isatty() if animate is None else animate
        self._file: TextIO | None = None
        self._lock = threading.Lock()

    def __enter__(self) -> AuditLogger:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.file_path.open("a", encoding="utf-8")
        self.file_event("audit_log_started", f"path={self.file_path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value is not None:
            self.file_event("audit_log_failed", f"error={exc_value}")
        self.file_event("audit_log_finished")
        if self._file is not None:
            self._file.close()
            self._file = None

    @contextmanager
    def step(self, message: str, *, detail: str | None = None, terminal: bool = True):
        """Record a step with terminal progress and file timestamps."""
        self.file_event(f"START {message}", detail)
        progress = _TerminalProgress(message, self.terminal, animate=self.animate) if terminal else None
        if progress is not None:
            progress.start()
        started = time.monotonic()
        try:
            yield
        except Exception as error:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if progress is not None:
                progress.finish(f"failed ({elapsed_ms} ms)")
            self.file_event(f"FAIL {message}", f"{detail or ''} error={error} elapsed_ms={elapsed_ms}".strip())
            raise
        else:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if progress is not None:
                progress.finish(f"done ({elapsed_ms} ms)")
            self.file_event(f"DONE {message}", f"{detail or ''} elapsed_ms={elapsed_ms}".strip())

    def terminal_event(self, message: str) -> None:
        """Print a single terminal event."""
        with self._lock:
            print(message, file=self.terminal)

    def file_event(self, message: str, detail: str | None = None) -> None:
        """Write a timestamped event to the audit file."""
        if self._file is None:
            return
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{timestamp} | {message}"
        if detail:
            line = f"{line} | {detail}"
        with self._lock:
            print(line, file=self._file)
            self._file.flush()

    def event(self, event: AuditEvent) -> None:
        """Write a detailed file-only event."""
        self.file_event(event.message, event.detail)


class NullAuditLogger:
    """No-op audit logger for unit tests and internal callers."""

    file_path = Path("")

    @contextmanager
    def step(self, message: str, *, detail: str | None = None, terminal: bool = True):
        yield

    def terminal_event(self, message: str) -> None:
        return None

    def file_event(self, message: str, detail: str | None = None) -> None:
        return None

    def event(self, event: AuditEvent) -> None:
        return None


class _TerminalProgress:
    def __init__(self, message: str, terminal: TextIO, *, animate: bool) -> None:
        self.message = message
        self.terminal = terminal
        self.animate = animate
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_text = ""

    def start(self) -> None:
        if self.animate:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return
        print(f"{self.message}...", file=self.terminal)

    def finish(self, status: str) -> None:
        if self.animate:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=1)
            clear = " " * max(len(self._last_text), len(self.message) + len(status) + 5)
            print(f"\r{clear}\r{self.message}... {status}", file=self.terminal)
            return
        print(f"{self.message}... {status}", file=self.terminal)

    def _run(self) -> None:
        dots = 0
        while not self._stop.is_set():
            dots = (dots % 4) + 1
            self._last_text = f"{self.message}{'.' * dots}"
            print(f"\r{self._last_text}", end="", file=self.terminal, flush=True)
            time.sleep(0.35)
