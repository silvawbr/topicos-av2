"""Local FastAPI console for running the AV2 judge pipeline."""

from __future__ import annotations

import csv
import re
import secrets
import shlex
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from .config import ConfigurationError
from .contracts import BatchProgress, EligibilitySummary, EvaluationProgress, PipelineSummary
from .dashboard import DashboardService, parse_dashboard_filters
from .database_dump import DatabaseDumpService, DatabaseResetService, resolve_dump_path
from .judge_clients.remote_http import RemoteJudgeError
from .parser import JudgeParseError
from .run_judge_service import RunJudgeRequest, RunJudgeResult, RunJudgeService


RunStatus = Literal["queued", "running", "cancelling", "completed", "failed", "cancelled"]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
AUDIT_TIMESTAMP_PATTERN = re.compile(r"^([^|]+)\s+\|\s+([^|]+)(?:\s+\|\s+(.*))?$")
AUDIT_KEY_VALUE_PATTERN = re.compile(r"([A-Za-z_]+)=([^ ]+)")
DEFAULT_AUDIT_DIR = Path("outputs") / "audit"
DEFAULT_BACKUP_DIR = Path("outputs") / "backup"


class RunPayload(BaseModel):
    panel_mode: Literal["single", "primary_only", "2plus1"] | None = None
    dataset: Literal["J1", "J2", "OAB_Bench", "OAB_Exames"] = "J2"
    batch_size: int | None = Field(default=None, ge=1)
    judge_execution_strategy: Literal["sequential", "parallel"] | None = None
    judge_model: str | None = None
    secondary_judge_model: str | None = None
    arbiter_judge_model: str | None = None
    always_run_arbiter: bool = False
    remote_judge_base_url: str | None = None
    remote_judge_api_key: str | None = None
    remote_secondary_judge_base_url: str | None = None
    remote_secondary_judge_api_key: str | None = None
    remote_arbiter_judge_base_url: str | None = None
    remote_arbiter_judge_api_key: str | None = None
    judge_arbitration_min_delta: int | None = Field(default=None, ge=0)
    remote_judge_timeout_seconds: int | None = Field(default=None, ge=1)
    remote_judge_temperature: float | None = Field(default=None, ge=0)
    remote_judge_max_tokens: int | None = Field(default=None, ge=1)
    remote_judge_top_p: float | None = Field(default=None, ge=0)
    remote_judge_openai_compatible: bool | None = None
    judge_save_raw_response: bool | None = None

    def to_request(self, *, dry_run: bool) -> RunJudgeRequest:
        return RunJudgeRequest(
            panel_mode=self.panel_mode,
            judge_model=self.judge_model or None,
            secondary_judge_model=self.secondary_judge_model or None,
            arbiter_judge_model=self.arbiter_judge_model or None,
            always_run_arbiter=self.always_run_arbiter,
            judge_execution_strategy=self.judge_execution_strategy,
            dataset=self.dataset,
            batch_size=self.batch_size,
            remote_judge_base_url=self.remote_judge_base_url or None,
            remote_judge_api_key=self.remote_judge_api_key or None,
            remote_secondary_judge_base_url=self.remote_secondary_judge_base_url or None,
            remote_secondary_judge_api_key=self.remote_secondary_judge_api_key or None,
            remote_arbiter_judge_base_url=self.remote_arbiter_judge_base_url or None,
            remote_arbiter_judge_api_key=self.remote_arbiter_judge_api_key or None,
            judge_arbitration_min_delta=self.judge_arbitration_min_delta,
            remote_judge_timeout_seconds=self.remote_judge_timeout_seconds,
            remote_judge_temperature=self.remote_judge_temperature,
            remote_judge_max_tokens=self.remote_judge_max_tokens,
            remote_judge_top_p=self.remote_judge_top_p,
            remote_judge_openai_compatible=self.remote_judge_openai_compatible,
            judge_save_raw_response=self.judge_save_raw_response,
            dry_run=dry_run,
            no_audit_animation=True,
        )


@dataclass
class JobState:
    run_id: str
    status: RunStatus
    request: RunJudgeRequest
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: BatchProgress = field(default_factory=lambda: _initial_progress())
    result: RunJudgeResult | None = None
    error: str | None = None
    audit_log: str | None = None
    command_preview: str | None = None
    eligibility: EligibilitySummary | None = None
    evaluation_events: list[EvaluationProgress] = field(default_factory=list)
    cancel_requested: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class RunHistoryEntry:
    run_id: str
    timestamp: str | None
    finished_at: str | None
    mode: str | None
    dataset: str | None
    batch_size: int | None
    successes: int
    failures: int
    duration_seconds: int | None
    duration: str | None
    log_path: str
    log_url: str
    summary: str | None


class JobRegistry:
    """In-memory job registry for a single local operator process."""

    def __init__(self, service: RunJudgeService) -> None:
        self.service = service
        self._jobs: dict[str, JobState] = {}
        self._active_run_id: str | None = None
        self._lock = threading.Lock()

    def create(self, request: RunJudgeRequest) -> JobState:
        resolved = self.service.resolve(request)
        with self._lock:
            if self._active_run_id is not None:
                active = self._jobs.get(self._active_run_id)
                if active is not None and active.status in {"queued", "running"}:
                    raise HTTPException(status_code=409, detail="Another judge run is already active.")
            run_id = uuid.uuid4().hex
            job = JobState(
                run_id=run_id,
                status="queued",
                request=request,
                audit_log=str(resolved.audit_path),
                command_preview=resolved.command_preview,
            )
            self._jobs[run_id] = job
            self._active_run_id = run_id
        threading.Thread(target=self._run, args=(run_id,), daemon=True).start()
        return job

    def get(self, run_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(run_id)

    def cancel(self, run_id: str) -> JobState | None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            if job.status in {"queued", "running", "cancelling"}:
                job.cancel_requested = True
                job.cancel_event.set()
                job.status = "cancelling"
                return job
            return job

    def _run(self, run_id: str) -> None:
        with self._lock:
            job = self._jobs[run_id]
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = datetime.now()
                if self._active_run_id == run_id:
                    self._active_run_id = None
                return
            job.status = "running"
            job.started_at = datetime.now()

        def update_progress(progress: BatchProgress) -> None:
            with self._lock:
                self._jobs[run_id].progress = progress

        def update_eligibility(eligibility: EligibilitySummary) -> None:
            with self._lock:
                self._jobs[run_id].eligibility = eligibility

        def update_evaluation(evaluation: EvaluationProgress) -> None:
            with self._lock:
                _upsert_evaluation_event(self._jobs[run_id].evaluation_events, evaluation)

        try:
            result = self.service.run(
                job.request,
                progress_callback=update_progress,
                eligibility_callback=update_eligibility,
                evaluation_callback=update_evaluation,
                should_stop=job.cancel_event.is_set,
            )
        except (ConfigurationError, RemoteJudgeError, JudgeParseError, RuntimeError, ValueError) as error:
            with self._lock:
                job = self._jobs[run_id]
                job.status = "failed"
                job.finished_at = datetime.now()
                job.error = str(error)
        else:
            with self._lock:
                job = self._jobs[run_id]
                job.status = "cancelled" if job.cancel_requested else "completed"
                job.finished_at = datetime.now()
                job.result = result
                job.audit_log = result.audit_log
                job.command_preview = result.command_preview
                job.eligibility = result.eligibility
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None


def create_app(
    service: RunJudgeService | None = None,
    *,
    audit_dir: Path | str = DEFAULT_AUDIT_DIR,
    backup_dir: Path | str = DEFAULT_BACKUP_DIR,
    dashboard_service: DashboardService | None = None,
    dump_service: DatabaseDumpService | None = None,
    database_reset_service: DatabaseResetService | None = None,
) -> FastAPI:
    app = FastAPI(title="Atividade 2 Judge Console")
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.jobs = JobRegistry(service or RunJudgeService())
    app.state.audit_dir = Path(audit_dir)
    app.state.backup_dir = Path(backup_dir)
    app.state.dashboard = dashboard_service or DashboardService()
    app.state.dump_service = dump_service or DatabaseDumpService(output_dir=backup_dir)
    app.state.database_reset_service = database_reset_service or DatabaseResetService()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    @app.get("/api/config")
    def get_config(request: Request) -> dict:
        config = request.app.state.jobs.service.describe_config()
        config["csrf_token"] = request.app.state.csrf_token
        return config

    @app.get("/api/dashboard")
    def get_dashboard(request: Request) -> dict:
        try:
            filters = parse_dashboard_filters(
                {
                    "dataset": request.query_params.get("dataset"),
                    "candidate_model": request.query_params.get("candidate_model"),
                    "judge_model": request.query_params.get("judge_model"),
                    "status": request.query_params.get("status"),
                    "date_from": request.query_params.get("date_from"),
                    "date_to": request.query_params.get("date_to"),
                    "group_by": request.query_params.get("group_by"),
                }
            )
            return request.app.state.dashboard.load(filters)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/runs/dry-run", dependencies=[Depends(_require_csrf)])
    def dry_run(payload: RunPayload, request: Request) -> dict:
        service: RunJudgeService = request.app.state.jobs.service
        try:
            result = service.run(payload.to_request(dry_run=True))
        except (ConfigurationError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _serialize_result(result)

    @app.post("/api/runs", dependencies=[Depends(_require_csrf)])
    def create_run(payload: RunPayload, request: Request) -> dict:
        registry: JobRegistry = request.app.state.jobs
        try:
            job = registry.create(payload.to_request(dry_run=False))
        except ConfigurationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _serialize_job(job)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict:
        registry: JobRegistry = request.app.state.jobs
        job = registry.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return _serialize_job(job)

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(_require_csrf)])
    def cancel_run(run_id: str, request: Request) -> dict:
        registry: JobRegistry = request.app.state.jobs
        job = registry.cancel(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return _serialize_job(job)

    @app.get("/api/runs/{run_id}/audit-log", response_class=PlainTextResponse)
    def get_audit_log(run_id: str, request: Request) -> str:
        registry: JobRegistry = request.app.state.jobs
        job = registry.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if not job.audit_log:
            raise HTTPException(status_code=404, detail="Audit log not available.")
        audit_path = Path(job.audit_log)
        if not audit_path.exists() or not audit_path.is_file():
            raise HTTPException(status_code=404, detail="Audit log file not found.")
        return audit_path.read_text(encoding="utf-8")

    @app.get("/api/run-history")
    def get_run_history(request: Request) -> list[dict]:
        return _list_run_history(request.app.state.audit_dir)

    @app.get("/api/run-history/export.json")
    def export_run_history_json(request: Request) -> list[dict]:
        return _list_run_history(request.app.state.audit_dir)

    @app.get("/api/run-history/export.csv")
    def export_run_history_csv(request: Request) -> Response:
        rows = _list_run_history(request.app.state.audit_dir)
        output = StringIO()
        fieldnames = [
            "run_id",
            "timestamp",
            "mode",
            "dataset",
            "batch_size",
            "successes",
            "failures",
            "duration",
            "log_path",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
        return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8")

    @app.get("/api/run-history/{run_id}/audit-log", response_class=PlainTextResponse)
    def get_run_history_audit_log(run_id: str, request: Request) -> str:
        audit_path = _resolve_history_log_path(request.app.state.audit_dir, run_id)
        if not audit_path.exists() or not audit_path.is_file():
            raise HTTPException(status_code=404, detail="Audit log file not found.")
        return audit_path.read_text(encoding="utf-8")

    @app.post("/api/database-dumps", dependencies=[Depends(_require_csrf)])
    def create_database_dump(request: Request) -> dict:
        try:
            result = request.app.state.dump_service.create_dump()
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return asdict(result)

    @app.post("/api/database-reset", dependencies=[Depends(_require_csrf)])
    def reset_database(request: Request) -> dict:
        try:
            return request.app.state.database_reset_service.reset_to_initial_state()
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/database-restore", dependencies=[Depends(_require_csrf)])
    async def restore_database_backup(request: Request) -> dict:
        filename = request.headers.get("x-backup-filename", "")
        if not filename.endswith(".sql"):
            raise HTTPException(status_code=400, detail="Selecione um arquivo .sql.")
        restore_dir = request.app.state.backup_dir / ".restore_uploads"
        restore_dir.mkdir(parents=True, exist_ok=True)
        restore_path = restore_dir / f"{uuid.uuid4()}_{Path(filename).name}"
        try:
            body = await request.body()
            if not body:
                raise HTTPException(status_code=400, detail="Arquivo de backup vazio.")
            restore_path.write_bytes(body)
            return request.app.state.database_reset_service.restore_backup(restore_path)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        finally:
            restore_path.unlink(missing_ok=True)

    @app.get("/api/database-dumps/{filename}")
    def download_database_dump(filename: str, request: Request) -> FileResponse:
        try:
            dump_path = resolve_dump_path(request.app.state.backup_dir, filename)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not dump_path.exists() or not dump_path.is_file():
            raise HTTPException(status_code=404, detail="Database dump file not found.")
        return FileResponse(
            dump_path,
            media_type="application/sql; charset=utf-8",
            filename=filename,
        )

    return app


def _require_csrf(request: Request) -> None:
    token = request.headers.get("x-csrf-token")
    if not token or token != request.app.state.csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _serialize_job(job: JobState) -> dict:
    return {
        "run_id": job.run_id,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at is not None else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at is not None else None,
        "duration_seconds": _duration_seconds(job.started_at, job.finished_at, 0),
        "duration": _format_duration(_duration_seconds(job.started_at, job.finished_at, 0)),
        "progress": asdict(job.progress),
        "audit_log": job.audit_log,
        "audit_log_url": f"/api/runs/{job.run_id}/audit-log" if job.audit_log else None,
        "command_preview": job.command_preview,
        "eligibility": asdict(job.eligibility) if job.eligibility is not None else None,
        "evaluation_events": [asdict(event) for event in job.evaluation_events],
        "error": job.error,
        "result": _serialize_result(job.result) if job.result is not None else None,
    }


def _serialize_result(result: RunJudgeResult) -> dict:
    return {
        "dry_run": result.dry_run,
        "audit_log": result.audit_log,
        "execution_summary": result.execution_summary,
        "command_preview": result.command_preview,
        "batch_size": result.batch_size,
        "eligibility": asdict(result.eligibility) if result.eligibility is not None else None,
        "summary": _serialize_summary(result.summary),
    }


def _serialize_summary(summary: PipelineSummary | None) -> dict | None:
    if summary is None:
        return None
    return asdict(summary)


def _list_run_history(audit_dir: Path) -> list[dict]:
    if not audit_dir.exists() or not audit_dir.is_dir():
        return []
    entries = [_parse_audit_log(path) for path in audit_dir.glob("*.log") if path.is_file()]
    entries.sort(key=lambda entry: entry.timestamp or "", reverse=True)
    return [asdict(entry) for entry in entries]


def _parse_audit_log(path: Path) -> RunHistoryEntry:
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    mode: str | None = None
    dataset: str | None = None
    batch_size: int | None = None
    successes = 0
    failures = 0
    summary: str | None = None
    elapsed_ms_total = 0

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = _parse_audit_line(line)
        if parsed is None:
            continue
        timestamp, message, detail = parsed
        first_timestamp = first_timestamp or timestamp
        last_timestamp = timestamp
        elapsed_ms_total += _extract_elapsed_ms(detail)
        if message == "execution_summary":
            summary = detail
            mode = _extract_summary_value(detail, "Judge mode")
        elif message == "command_preview":
            dataset = _extract_cli_arg(detail, "--dataset") or dataset
            batch_size = _parse_int(_extract_cli_arg(detail, "--batch-size")) or batch_size
        elif message.startswith("START Counting eligible answers for ") or message.startswith(
            "START Selecting pending candidate answers for "
        ):
            values = _key_values(detail)
            dataset = values.get("dataset") or dataset
            batch_size = _parse_int(values.get("batch_size")) or batch_size
        elif message == "execution_result":
            values = _key_values(detail)
            successes = _parse_int(values.get("executed")) or successes
        if _is_failure_event(message, detail):
            failures += 1

    duration_seconds = _duration_seconds(first_timestamp, last_timestamp, elapsed_ms_total)
    run_id = path.stem
    return RunHistoryEntry(
        run_id=run_id,
        timestamp=first_timestamp.isoformat() if first_timestamp is not None else None,
        finished_at=last_timestamp.isoformat() if last_timestamp is not None else None,
        mode=mode,
        dataset=dataset,
        batch_size=batch_size,
        successes=successes,
        failures=failures,
        duration_seconds=duration_seconds,
        duration=_format_duration(duration_seconds),
        log_path=str(path),
        log_url=f"/api/run-history/{run_id}/audit-log",
        summary=summary,
    )


def _parse_audit_line(line: str) -> tuple[datetime, str, str | None] | None:
    match = AUDIT_TIMESTAMP_PATTERN.match(line)
    if not match:
        return None
    try:
        timestamp = datetime.fromisoformat(match.group(1).strip())
    except ValueError:
        return None
    return timestamp, match.group(2).strip(), match.group(3).strip() if match.group(3) else None


def _extract_summary_value(summary: str | None, label: str) -> str | None:
    if not summary:
        return None
    prefix = f"{label}: "
    for part in (value.strip() for value in summary.split("|")):
        if part.startswith(prefix):
            return part.removeprefix(prefix).strip()
    return None


def _extract_cli_arg(command: str | None, option: str) -> str | None:
    if not command:
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    for index, part in enumerate(parts[:-1]):
        if part == option:
            return parts[index + 1]
    return None


def _key_values(detail: str | None) -> dict[str, str]:
    if not detail:
        return {}
    return {match.group(1): match.group(2) for match in AUDIT_KEY_VALUE_PATTERN.finditer(detail)}


def _extract_elapsed_ms(detail: str | None) -> int:
    return _parse_int(_key_values(detail).get("elapsed_ms")) or 0


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_failure_event(message: str, detail: str | None) -> bool:
    if message.startswith("FAIL ") or message == "audit_log_failed":
        return True
    return "status=failed" in (detail or "")


def _duration_seconds(
    first_timestamp: datetime | None,
    last_timestamp: datetime | None,
    elapsed_ms_total: int,
) -> int | None:
    if first_timestamp is not None and last_timestamp is not None:
        return max(0, round((last_timestamp - first_timestamp).total_seconds()))
    if elapsed_ms_total:
        return round(elapsed_ms_total / 1000)
    return None


def _format_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    minutes, remaining_seconds = divmod(seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{remaining_minutes:02d}min{remaining_seconds:02d}s"
    if minutes:
        return f"{minutes}min{remaining_seconds:02d}s"
    return f"{remaining_seconds}s"


def _resolve_history_log_path(audit_dir: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id.")
    root = audit_dir.resolve()
    path = (root / f"{run_id}.log").resolve()
    if path.parent != root:
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return path


def _upsert_evaluation_event(events: list[EvaluationProgress], event: EvaluationProgress) -> None:
    event_key = _evaluation_event_key(event)
    for index, existing in enumerate(events):
        if _evaluation_event_key(existing) == event_key:
            events[index] = event
            return
    events.append(event)


def _evaluation_event_key(event: EvaluationProgress) -> tuple:
    return (
        event.dataset,
        event.question_id,
        event.answer_id,
        event.candidate_model,
        event.judge_model,
        event.role,
        event.panel_mode,
        event.trigger_reason,
    )


def _initial_progress() -> BatchProgress:
    return BatchProgress(
        current=0,
        total=0,
        percent=0,
        executed_evaluations=0,
        skipped_evaluations=0,
        arbiter_evaluations=0,
    )


_INDEX_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atividade 2 Judge Console</title>
  <style>
    :root { color-scheme: light; --ink:#18212f; --muted:#5b6472; --line:#d8dde6; --bg:#f6f7f9; --accent:#1769aa; --ok:#1d7f4e; --bad:#b42318; --warn:#9a5b00; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 28px 12px; border-bottom:1px solid var(--line); background:#fff; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    .tabs { display:flex; gap:8px; padding:12px 28px 0; background:#fff; border-bottom:1px solid var(--line); }
    .tab-button { min-height:34px; color:var(--muted); background:#fff; border-color:transparent; border-bottom:2px solid transparent; border-radius:0; }
    .tab-button.active { color:var(--accent); border-bottom-color:var(--accent); }
    .tab-panel[hidden] { display:none; }
    main { width:min(100%, 1440px); margin:0 auto; padding:20px; display:grid; grid-template-columns: minmax(320px,380px) minmax(0,1fr); gap:18px; }
    section, aside { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; }
    section, aside { min-width:0; }
    aside { padding-bottom:82px; }
    h2 { font-size:15px; margin:0 0 12px; }
    label { display:grid; gap:5px; margin:10px 0; color:var(--muted); font-size:12px; }
    input, select { width:100%; min-height:36px; border:1px solid var(--line); border-radius:6px; padding:7px 9px; font:inherit; color:var(--ink); background:#fff; }
    button { border:1px solid var(--accent); background:var(--accent); color:#fff; border-radius:6px; min-height:36px; padding:0 12px; font-weight:650; cursor:pointer; }
    .button-link { display:inline-flex; align-items:center; min-height:32px; padding:0 10px; border:1px solid var(--accent); border-radius:6px; color:var(--accent); background:#fff; font-size:12px; font-weight:650; text-decoration:none; }
    button.secondary { color:var(--accent); background:#fff; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .judge-block { border-top:1px solid var(--line); padding-top:10px; margin-top:10px; }
    .endpoint-fields[hidden] { display:none; }
    .secret-row { display:grid; grid-template-columns:1fr 38px; gap:8px; align-items:center; }
    .icon-button { min-height:36px; padding:0; border-color:var(--line); background:#fff; color:var(--ink); font-size:16px; font-weight:500; }
    .inline { display:flex; align-items:center; gap:8px; margin:8px 0; color:var(--muted); font-size:12px; }
    .inline input { width:auto; min-height:auto; }
    .hint { color:var(--muted); font-size:12px; line-height:1.35; margin:-4px 0 8px; }
    .warn { color:var(--warn); }
    details { border-top:1px solid var(--line); margin-top:12px; padding-top:10px; }
    summary { cursor:pointer; color:var(--ink); font-size:13px; font-weight:650; }
    .status-icon { display:inline-grid; place-items:center; width:18px; height:18px; margin-right:6px; vertical-align:-3px; }
    .spinner { border:2px solid #c9d2de; border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }
    .actions { position:sticky; bottom:0; display:flex; gap:10px; margin:14px -16px -16px; padding:12px 16px; border-top:1px solid var(--line); background:#fff; border-radius:0 0 8px 8px; }
    .actions button { flex:1; }
    .presets { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }
    .presets button { min-height:32px; font-size:12px; }
    .status { font-size:13px; color:var(--muted); }
    pre { max-width:100%; overflow:auto; background:#101828; color:#f9fafb; border-radius:6px; padding:12px; min-height:76px; white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; }
    progress { width:100%; height:22px; accent-color:var(--accent); }
    table { width:100%; border-collapse:collapse; margin-top:12px; font-size:13px; }
    th, td { text-align:left; border-bottom:1px solid var(--line); padding:8px; }
    .table-wrap { width:100%; max-width:100%; overflow:auto; border:1px solid var(--line); border-radius:8px; margin-top:12px; }
    .table-wrap table { min-width:1180px; margin-top:0; }
    .history-layout { width:min(100%, 1440px); margin:0 auto; padding:20px; display:grid; grid-template-columns:minmax(0,1fr) minmax(320px,480px); gap:18px; }
    .history-actions { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
    .history-actions div { display:flex; gap:8px; }
    .history-row { cursor:pointer; }
    .history-row:hover { background:#f7fbff; }
    .history-log { min-height:520px; max-height:calc(100vh - 260px); }
    .history-export-links { display:flex; gap:8px; white-space:nowrap; }
    .audit-log-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; }
    .audit-log-row a { overflow-wrap:anywhere; }
    .audit-log-button { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:30px; padding:0 9px; border-color:var(--line); background:#fff; color:var(--accent); font-size:12px; white-space:nowrap; }
    .audit-log-button-icon { font-size:15px; line-height:1; }
    .audit-log-button:disabled { color:var(--muted); }
    .audit-log-content { min-height:420px; max-height:calc(100vh - 210px); margin:0; overflow:auto; }
    .dashboard-layout { width:min(100%, 1440px); margin:0 auto; padding:20px; display:grid; grid-template-columns:minmax(280px,340px) minmax(0,1fr); gap:18px; }
    .dashboard-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
    .dashboard-head p { margin:4px 0 0; color:var(--muted); font-size:13px; line-height:1.4; }
    .dashboard-actions { position:relative; display:flex; flex-direction:column; align-items:flex-end; gap:6px; min-width:230px; }
    .database-actions-toggle { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-width:174px; min-height:38px; padding:0 12px; border-color:var(--accent); background:var(--accent); color:#fff; font-size:13px; font-weight:750; box-shadow:0 6px 14px rgba(23,105,170,.22); }
    .database-actions-toggle-icon { font-size:17px; line-height:1; }
    .database-actions-toggle-caret { font-size:11px; line-height:1; opacity:.9; }
    .database-actions-menu { position:absolute; top:42px; right:0; z-index:20; display:grid; gap:4px; width:240px; padding:6px; border:1px solid var(--line); border-radius:8px; background:#fff; box-shadow:0 12px 28px rgba(16,24,40,.14); }
    .database-actions-menu[hidden] { display:none; }
    .database-actions-menu button { width:100%; min-height:34px; border-color:transparent; background:#fff; color:var(--ink); text-align:left; font-size:13px; }
    .database-actions-menu button:hover { background:#f2f8fd; color:var(--accent); }
    .database-actions-menu button.danger { color:var(--bad); }
    .database-actions-menu button.danger:hover { background:#fff5f5; }
    .dashboard-filters select[multiple] { min-height:92px; }
    .dashboard-filter-actions { display:flex; gap:8px; margin-top:12px; }
    .dashboard-filter-actions button { flex:1; }
    .dashboard-note { color:var(--muted); font-size:12px; line-height:1.45; margin-top:10px; }
    .dashboard-table table { min-width:960px; }
    .post-run-panel { margin-top:18px; border-top:1px solid var(--line); padding-top:16px; }
    .metric-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px,1fr)); gap:10px; margin:10px 0 16px; }
    .metric-card { border:1px solid var(--line); border-radius:8px; padding:10px; background:#fbfcfe; min-width:0; }
    .metric-value { display:block; font-size:22px; font-weight:750; line-height:1.15; overflow-wrap:anywhere; }
    .metric-label { display:block; color:var(--muted); font-size:12px; margin-top:3px; }
    .chart-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px,1fr)); gap:14px; }
    .chart { border:1px solid var(--line); border-radius:8px; padding:12px; min-width:0; }
    .chart h3 { margin:0 0 10px; font-size:13px; }
    .bar-row { display:grid; grid-template-columns:minmax(82px,132px) minmax(88px,1fr) 104px; gap:8px; align-items:center; margin:7px 0; font-size:12px; }
    .bar-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); }
    .bar-track { height:14px; border-radius:999px; background:#e5e9f0; overflow:hidden; box-shadow:inset 0 0 0 1px rgba(24,33,47,.03); }
    .bar-fill { height:100%; min-width:4px; border-radius:999px; background:linear-gradient(90deg, #1769aa, #1d7f4e); }
    .bar-fill.score-1 { background:#b42318; }
    .bar-fill.score-2 { background:#d97706; }
    .bar-fill.score-3 { background:#1769aa; }
    .bar-fill.score-4 { background:#1d7f4e; }
    .bar-fill.score-5 { background:#0f766e; }
    .bar-fill.failed { background:#b42318; }
    .bar-fill.arbiter { background:#7c3aed; }
    .bar-fill.none { background:#64748b; }
    .bar-fill.zero { min-width:0; }
    .bar-value { display:grid; grid-template-columns:42px 54px; justify-content:end; align-items:center; gap:6px; font-variant-numeric:tabular-nums; color:var(--ink); font-weight:800; white-space:nowrap; font-size:13px; }
    .bar-count { --pill-fill:#1769aa; --pill-bg:#eaf3fb; --pill-pct:0%; width:42px; text-align:center; border-radius:999px; padding:2px 0; color:var(--accent); background:linear-gradient(90deg, color-mix(in srgb, var(--pill-fill) 26%, white) 0 var(--pill-pct), var(--pill-bg) var(--pill-pct) 100%); }
    .bar-count.positive { --pill-fill:#1d7f4e; --pill-bg:#e7f7ee; color:var(--ok); }
    .bar-count.warning { --pill-fill:#9a5b00; --pill-bg:#fff4df; color:var(--warn); }
    .bar-count.bad { --pill-fill:#b42318; --pill-bg:#fff1f0; color:var(--bad); }
    .bar-percent { color:var(--muted); font-weight:600; text-align:right; }
    .badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 7px; font-size:12px; white-space:nowrap; }
    .badge.success { color:var(--ok); border-color:#b7dfc8; background:#f0fbf4; }
    .badge.failed { color:var(--bad); border-color:#f0b8b2; background:#fff5f5; }
    .badge.running { color:var(--accent); border-color:#b9d5eb; background:#f2f8fd; }
    .badge.skipped { color:var(--warn); border-color:#ead0a6; background:#fff8eb; }
    .detail-button { min-height:30px; padding:0 9px; border-color:var(--line); background:#fff; color:var(--accent); font-size:12px; }
    dialog { width:min(900px, calc(100vw - 28px)); border:1px solid var(--line); border-radius:8px; padding:0; }
    dialog::backdrop { background:rgba(16,24,40,.42); }
    .dialog-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border-bottom:1px solid var(--line); }
    .dialog-body { padding:14px; }
    .dialog-body h3 { margin:12px 0 6px; font-size:13px; }
    .confirm-dialog { width:min(520px, calc(100vw - 28px)); }
    .confirm-dialog .dialog-body { display:grid; gap:10px; }
    .confirm-dialog p { margin:0; color:var(--muted); font-size:13px; line-height:1.45; }
    .confirm-actions { display:flex; justify-content:flex-end; align-items:center; gap:8px; padding:12px 14px; border-top:1px solid var(--line); }
    .confirm-actions button { min-width:96px; white-space:nowrap; }
    .confirm-actions .backup-clean-button { min-width:206px; }
    .danger-button { border-color:var(--bad); background:var(--bad); color:#fff; }
    .ok { color:var(--ok); }
    .bad { color:var(--bad); }
    .muted { color:var(--muted); }
    @media (max-width: 860px) { main, .history-layout, .dashboard-layout { grid-template-columns:minmax(0,1fr); padding:12px; } .dashboard-head { flex-direction:column; } .dashboard-actions { align-items:stretch; width:100%; } }
  </style>
</head>
<body>
  <header>
    <h1>Atividade 2 Judge Console</h1>
    <div id="config-status" class="status">Carregando configuracao local...</div>
  </header>
  <nav class="tabs" aria-label="Navegacao principal">
    <button class="tab-button active" type="button" data-tab="dashboard-panel">Dashboard</button>
    <button class="tab-button" type="button" data-tab="execution-panel">Execucao</button>
    <button class="tab-button" type="button" data-tab="history-panel">Execucoes anteriores</button>
  </nav>
  <main id="dashboard-panel" class="dashboard-layout tab-panel">
    <aside class="dashboard-filters">
      <h2>Filtros globais</h2>
      <label>Dataset
        <select id="dashboard_dataset"><option value="J1">J1</option><option value="J2">J2</option><option value="all">Todos</option></select>
      </label>
      <label>Modelo candidato
        <select id="dashboard_candidate_model" multiple></select>
      </label>
      <label>Modelo juiz
        <select id="dashboard_judge_model" multiple></select>
      </label>
      <label>Status
        <select id="dashboard_status"><option value="all">todos</option><option value="sucesso">sucesso</option><option value="erro">erro</option></select>
      </label>
      <label>Agrupamento
        <select id="dashboard_group_by"><option value="modelo">por modelo</option><option value="juiz">por juiz</option><option value="dataset">por dataset</option><option value="disciplina">por disciplina</option><option value="dificuldade">por dificuldade</option></select>
      </label>
      <div class="dashboard-filter-actions">
        <button id="dashboard-refresh" type="button">Atualizar</button>
        <button id="dashboard-clear" class="secondary" type="button">Limpar</button>
      </div>
      <p class="dashboard-note">J1 e o dataset padrao. Spearman principal em J1 so aparece quando houver nota de referencia ordinal persistida; juiz x arbitro e exibido separadamente como consistencia.</p>
    </aside>
    <section>
      <div class="dashboard-head">
        <div>
          <h2>Resultados e Auditoria da Avaliacao</h2>
          <p>Visao consolidada das avaliacoes LLM-as-a-Judge, correlacao, distribuicao de notas e analise de erros.</p>
        </div>
        <div class="dashboard-actions">
          <button id="database-actions-toggle" class="database-actions-toggle" type="button" aria-haspopup="menu" aria-expanded="false" title="Acoes do banco">
            <span class="database-actions-toggle-icon" aria-hidden="true">&#9881;</span>
            <span>Acoes do Banco</span>
            <span class="database-actions-toggle-caret" aria-hidden="true">▼</span>
          </button>
          <div id="database-actions-menu" class="database-actions-menu" role="menu" hidden>
            <button id="database-clean" class="danger" type="button" role="menuitem">Clean DB (Initial State)</button>
            <button id="database-restore" type="button" role="menuitem">Restaurar Backup</button>
            <button id="database-dump" type="button" role="menuitem">Exportar Dump do Banco</button>
          </div>
          <input id="database-restore-file" type="file" accept=".sql,application/sql,text/plain" hidden>
          <span id="database-dump-status" class="status"></span>
        </div>
      </div>
      <div id="dashboard-cards" class="metric-grid"></div>
      <div class="chart-grid">
        <div class="chart">
          <h3>Ranking geral dos modelos candidatos</h3>
          <div id="dashboard-candidate-ranking"></div>
        </div>
        <div class="chart">
          <h3>Distribuicao de notas 1-5</h3>
          <div id="dashboard-score-distribution"></div>
        </div>
        <div class="chart">
          <h3>Media por juiz</h3>
          <div id="dashboard-judge-average"></div>
        </div>
        <div class="chart">
          <h3>Divergencias para auditoria</h3>
          <div id="dashboard-divergences"></div>
        </div>
        <div class="chart">
          <h3>Casos criticos</h3>
          <div id="dashboard-critical-chart"></div>
        </div>
      </div>
      <p id="dashboard-methodology" class="dashboard-note"></p>
      <h2 style="margin-top:18px">Casos criticos e divergencias</h2>
      <div class="table-wrap dashboard-table">
        <table aria-label="Casos criticos do dashboard">
          <thead>
            <tr>
              <th>motivo</th>
              <th>dataset</th>
              <th>id_resposta</th>
              <th>id_pergunta</th>
              <th>modelo_candidato</th>
              <th>juiz</th>
              <th>papel</th>
              <th>nota</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody id="dashboard-cases-body">
            <tr><td colspan="9" class="muted">Carregando dashboard.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
  <main id="execution-panel" class="tab-panel" hidden>
    <aside>
      <h2>Presets</h2>
      <div id="presets" class="presets"></div>
      <h2>Configuracao</h2>
      <label>Modo
        <select id="panel_mode"><option>single</option><option>primary_only</option><option>2plus1</option></select>
      </label>
      <div class="row">
        <label>Dataset
          <select id="dataset"><option>J2</option><option>J1</option></select>
        </label>
        <label>Batch size
          <input id="batch_size" type="number" min="1" value="10">
        </label>
      </div>
      <label>Estrategia
        <select id="judge_execution_strategy"><option>sequential</option><option>parallel</option></select>
      </label>
      <div class="hint">Sequential e melhor para endpoint local ou fragil. Parallel e indicado para endpoint remoto que aceita concorrencia.</div>
      <div class="judge-block">
      <label>Juiz 1 - modelo
        <input id="judge_model" autocomplete="off">
      </label>
      <label>Endpoint do juiz 1
        <select id="endpoint_source_judge"><option value="env">Usar .env</option><option value="custom">Config propria</option></select>
      </label>
      <div id="endpoint_fields_judge" class="endpoint-fields" hidden>
      <label>Juiz 1 - URL
        <input id="remote_judge_base_url" autocomplete="off" placeholder="usa REMOTE_JUDGE_BASE_URL se vazio">
      </label>
      <label>Juiz 1 - token/key
        <span class="secret-row">
          <input id="remote_judge_api_key" type="password" autocomplete="off" placeholder="usa REMOTE_JUDGE_API_KEY se vazio">
          <button class="icon-button" type="button" data-toggle-secret="remote_judge_api_key" aria-label="Exibir token/key do juiz 1" aria-pressed="false">◉</button>
        </span>
      </label>
      </div>
      </div>
      <div class="judge-block">
      <label>Juiz 2 - modelo
        <input id="secondary_judge_model" autocomplete="off">
      </label>
      <label>Endpoint do juiz 2
        <select id="endpoint_source_secondary"><option value="env">Usar .env</option><option value="judge">Copiar do juiz 1</option><option value="custom">Config propria</option></select>
      </label>
      <div id="endpoint_fields_secondary" class="endpoint-fields" hidden>
      <label>Juiz 2 - URL
        <input id="remote_secondary_judge_base_url" autocomplete="off" placeholder="usa endpoint global se vazio">
      </label>
      <label>Juiz 2 - token/key
        <span class="secret-row">
          <input id="remote_secondary_judge_api_key" type="password" autocomplete="off" placeholder="usa token global se vazio">
          <button class="icon-button" type="button" data-toggle-secret="remote_secondary_judge_api_key" aria-label="Exibir token/key do juiz 2" aria-pressed="false">◉</button>
        </span>
      </label>
      </div>
      </div>
      <div class="judge-block">
      <label>Arbitro - modelo
        <input id="arbiter_judge_model" autocomplete="off">
      </label>
      <label>Endpoint do arbitro
        <select id="endpoint_source_arbiter"><option value="env">Usar .env</option><option value="judge">Copiar do juiz 1</option><option value="secondary">Copiar do juiz 2</option><option value="custom">Config propria</option></select>
      </label>
      <div id="endpoint_fields_arbiter" class="endpoint-fields" hidden>
      <label>Arbitro - URL
        <input id="remote_arbiter_judge_base_url" autocomplete="off" placeholder="usa endpoint global se vazio">
      </label>
      <label>Arbitro - token/key
        <span class="secret-row">
          <input id="remote_arbiter_judge_api_key" type="password" autocomplete="off" placeholder="usa token global se vazio">
          <button class="icon-button" type="button" data-toggle-secret="remote_arbiter_judge_api_key" aria-label="Exibir token/key do arbitro" aria-pressed="false">◉</button>
        </span>
      </label>
      </div>
      </div>
      <label class="inline"><input id="judge_save_raw_response" type="checkbox"> Salvar resposta bruta do juiz</label>
      <details>
        <summary>Campos avancados</summary>
        <label class="inline"><input id="always_run_arbiter" type="checkbox"> Rodar arbitro sempre <span class="warn">aumenta custo e chamadas remotas</span></label>
        <div class="row">
          <label>Timeout (s)
            <input id="remote_judge_timeout_seconds" type="number" min="1">
          </label>
          <label>Arbitration min delta
            <input id="judge_arbitration_min_delta" type="number" min="0">
          </label>
        </div>
        <div class="row">
          <label>Temperature
            <input id="remote_judge_temperature" type="number" min="0" step="0.1">
          </label>
          <label>Max tokens
            <input id="remote_judge_max_tokens" type="number" min="1">
          </label>
        </div>
        <div class="row">
          <label>Top P
            <input id="remote_judge_top_p" type="number" min="0" step="0.1">
          </label>
          <label>OpenAI compatible
            <select id="remote_judge_openai_compatible"><option value="true">true</option><option value="false">false</option></select>
          </label>
        </div>
      </details>
      <div class="actions">
        <button class="secondary" id="dry-run" disabled>Validar configuracao</button>
        <button class="secondary" id="stop-run" type="button" disabled>Parar</button>
        <button id="run" disabled>Executar</button>
      </div>
    </aside>
    <section>
      <h2>Execucao</h2>
      <progress id="batch-progress" max="100" value="0"></progress>
      <div id="progress-label" class="status">0% - aguardando execucao</div>
      <table>
        <tbody>
          <tr><th>Status</th><td><span id="run-status-icon" class="status-icon">-</span><span id="run-status">idle</span></td></tr>
          <tr><th>Audit log</th><td id="audit-log" class="muted">-</td></tr>
          <tr><th>Missing</th><td id="eligible-missing">-</td></tr>
          <tr><th>Failed</th><td id="eligible-failed">-</td></tr>
          <tr><th>Ja avaliadas com sucesso</th><td id="eligible-successful">-</td></tr>
          <tr><th>Serao processadas neste batch</th><td id="eligible-will-process">-</td></tr>
          <tr><th>Selecionadas</th><td id="selected">-</td></tr>
          <tr><th>Executadas</th><td id="executed">-</td></tr>
          <tr><th>Puladas</th><td id="skipped">-</td></tr>
          <tr><th>Arbitragens</th><td id="arbiters">-</td></tr>
        </tbody>
      </table>
      <h2 style="margin-top:18px">Comando equivalente</h2>
      <pre id="command-preview"></pre>
      <h2>Resumo / erro</h2>
      <pre id="output"></pre>
      <div id="post-run-panel" class="post-run-panel" hidden>
        <h2>Batch finalizado</h2>
        <div id="post-run-cards" class="metric-grid"></div>
        <div class="chart-grid">
          <div class="chart">
            <h3>Distribuicao de notas 1-5</h3>
            <div id="score-distribution-chart"></div>
          </div>
          <div class="chart">
            <h3>Falhas por juiz</h3>
            <div id="judge-failures-chart"></div>
          </div>
          <div class="chart">
            <h3>Arbitragens</h3>
            <div id="arbitration-chart"></div>
          </div>
          <div class="chart">
            <h3>Media por modelo candidato</h3>
            <div id="candidate-average-chart"></div>
          </div>
          <div class="chart">
            <h3>Media por juiz</h3>
            <div id="judge-average-chart"></div>
          </div>
        </div>
      </div>
      <h2 style="margin-top:18px">Tabela dinamica de execucao</h2>
      <div class="table-wrap">
        <table aria-label="Tabela dinamica de execucao">
          <thead>
            <tr>
              <th>status</th>
              <th>dataset</th>
              <th>id_pergunta</th>
              <th>modelo_candidato</th>
              <th>juiz</th>
              <th>papel</th>
              <th>nota</th>
              <th>delta</th>
              <th>arbitro acionado?</th>
              <th>motivo_acionamento</th>
              <th>latencia</th>
              <th>erro</th>
              <th>ver detalhes</th>
            </tr>
          </thead>
          <tbody id="execution-table-body">
            <tr><td colspan="13" class="muted">Aguardando execucao.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
  <div id="history-panel" class="history-layout tab-panel" hidden>
    <section>
      <div class="history-actions">
        <h2>Execucoes anteriores</h2>
        <div>
          <a class="button-link" href="/api/run-history/export.csv" download="run-history.csv">CSV</a>
          <a class="button-link" href="/api/run-history/export.json" download="run-history.json">JSON</a>
        </div>
      </div>
      <div class="table-wrap">
        <table aria-label="Tabela de execucoes anteriores">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Data/hora</th>
              <th>Modo</th>
              <th>Dataset</th>
              <th>Batch size</th>
              <th>Sucessos</th>
              <th>Falhas</th>
              <th>Duracao</th>
              <th>Log</th>
              <th>Exportar</th>
            </tr>
          </thead>
          <tbody id="history-table-body">
            <tr><td colspan="10" class="muted">Carregando historico.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <aside>
      <h2>Log</h2>
      <table>
        <tbody>
          <tr><th>Run ID</th><td id="history-log-run-id" class="muted">Selecione uma execucao.</td></tr>
          <tr><th>Arquivo</th><td id="history-log-path" class="muted">-</td></tr>
        </tbody>
      </table>
      <pre id="history-log-content" class="history-log">Selecione uma execucao.</pre>
    </aside>
  </div>
  <dialog id="details-dialog">
    <div class="dialog-head">
      <strong id="details-title">Detalhes da avaliacao</strong>
      <button class="secondary" id="details-close" type="button">Fechar</button>
    </div>
    <div class="dialog-body">
      <h3>Prompt</h3>
      <pre id="details-prompt"></pre>
      <h3>Resposta do juiz</h3>
      <pre id="details-response"></pre>
      <h3>Justificativa</h3>
      <pre id="details-rationale"></pre>
    </div>
  </dialog>
  <dialog id="audit-log-dialog">
    <div class="dialog-head">
      <strong>Live audit log</strong>
      <button class="secondary" id="audit-log-close" type="button">Fechar</button>
    </div>
    <div class="dialog-body">
      <pre id="audit-log-content" class="audit-log-content">Audit log nao selecionado.</pre>
    </div>
  </dialog>
  <dialog id="database-clean-dialog" class="confirm-dialog">
    <div class="dialog-head">
      <strong>Clean DB (Initial State)</strong>
    </div>
    <div class="dialog-body">
      <p>Resetar o banco para o estado inicial?</p>
      <p>Isso limpa o schema public, restaura backup_atividade_2.sql e valida o restore.</p>
    </div>
    <div class="confirm-actions">
      <button id="database-clean-cancel" class="secondary" type="button">Cancelar</button>
      <button id="database-clean-backup-confirm" class="secondary backup-clean-button" type="button">Fazer backup e limpar</button>
      <button id="database-clean-confirm" class="danger-button" type="button">Limpar</button>
    </div>
  </dialog>
  <dialog id="database-dump-dialog" class="confirm-dialog">
    <div class="dialog-head">
      <strong>Backup salvo</strong>
      <button id="database-dump-dialog-close" class="secondary" type="button">Fechar</button>
    </div>
    <div class="dialog-body">
      <p>O dump do banco foi criado com sucesso.</p>
      <table>
        <tbody>
          <tr><th>Arquivo</th><td id="database-dump-filename"></td></tr>
          <tr><th>Caminho</th><td id="database-dump-path"></td></tr>
          <tr><th>Tamanho</th><td id="database-dump-size"></td></tr>
        </tbody>
      </table>
    </div>
  </dialog>
  <script>
    let csrfToken = "";
    let pollTimer = null;
    let historyLoaded = false;
    let dashboardLoaded = false;
    let currentAuditLogUrl = null;
    let activeRunId = null;

    function value(id) { return document.getElementById(id).value; }
    function setText(id, text) { document.getElementById(id).textContent = text ?? "-"; }
    function display(value) { return value === null || value === undefined || value === "" ? "-" : value; }
    function friendlyErrorMessage(message) {
      const raw = String(message || "");
      const normalized = raw.toLowerCase();
      const mappings = [
        ["REMOTE_JUDGE_BASE_URL is required", "Configure a URL do endpoint do juiz"],
        ["REMOTE_JUDGE_API_KEY is required", "Configure a key local; não commitar"],
        ["invalid JSON", "O modelo não respeitou o contrato de saída"],
        ["model does not exist", "Modelo inválido ou sem acesso nesse provedor"],
        ["HTTP 401", "key inválida ou sem permissão"],
        ["HTTP 403", "key inválida ou sem permissão"],
        ["HTTP 404", "base URL/modelo incorreto"]
      ];
      for (const [needle, friendly] of mappings) {
        if (normalized.includes(needle.toLowerCase())) return friendly;
      }
      if (normalized.includes("timeout")) return "aumentar timeout ou reduzir batch";
      return raw || "Erro desconhecido.";
    }

    function formatDateTime(value) {
      if (!value) return "-";
      return new Date(value).toLocaleString();
    }

    function selectedValues(id) {
      return Array.from(document.getElementById(id).selectedOptions).map((option) => option.value).filter(Boolean);
    }

    function dashboardQuery() {
      const params = new URLSearchParams();
      params.set("dataset", value("dashboard_dataset"));
      params.set("status", value("dashboard_status"));
      params.set("group_by", value("dashboard_group_by"));
      const candidates = selectedValues("dashboard_candidate_model");
      const judges = selectedValues("dashboard_judge_model");
      if (candidates.length) params.set("candidate_model", candidates.join(","));
      if (judges.length) params.set("judge_model", judges.join(","));
      return params.toString();
    }

    async function loadDashboard() {
      const body = document.getElementById("dashboard-cases-body");
      body.innerHTML = '<tr><td colspan="9" class="muted">Carregando dashboard.</td></tr>';
      try {
        const response = await fetch(`/api/dashboard?${dashboardQuery()}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Dashboard indisponivel.");
        dashboardLoaded = true;
        renderDashboard(data);
      } catch (error) {
        body.innerHTML = "";
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 9;
        cell.className = "muted";
        cell.textContent = friendlyErrorMessage(error.message);
        row.appendChild(cell);
        body.appendChild(row);
      }
    }

    function renderDashboard(data) {
      populateSelect("dashboard_candidate_model", data.options?.candidate_models || [], selectedValues("dashboard_candidate_model"));
      populateSelect("dashboard_judge_model", data.options?.judge_models || [], selectedValues("dashboard_judge_model"));
      renderDashboardCards(data.cards || {});
      renderBarChart("dashboard-candidate-ranking", data.charts?.candidate_ranking || [], {scaleMax: 5});
      renderBarChart("dashboard-score-distribution", data.charts?.score_distribution || [], {scaleMax: 1, showPercent: true, colorByLabel: true});
      renderBarChart("dashboard-judge-average", data.charts?.judge_average || [], {scaleMax: 5});
      renderBarChart("dashboard-divergences", data.charts?.divergences || [], {scaleMax: 1, tone: "bad"});
      renderBarChart("dashboard-critical-chart", data.charts?.critical_cases || [], {scaleMax: 1, tone: "bad"});
      setText("dashboard-methodology", `${data.methodology?.primary_spearman || ""} ${data.methodology?.judge_arbiter || ""}`.trim());
      renderDashboardCases([...(data.tables?.critical_cases || []), ...(data.tables?.divergence_cases || [])]);
    }

    function populateSelect(id, values, selected) {
      const select = document.getElementById(id);
      const selectedSet = new Set(selected || []);
      select.textContent = "";
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = selectedSet.has(value);
        select.appendChild(option);
      }
    }

    function renderDashboardCards(cards) {
      const root = document.getElementById("dashboard-cards");
      root.textContent = "";
      const coverage = cards.coverage || {};
      const metrics = [
        ["Avaliacoes realizadas", cards.evaluations],
        ["Cobertura do dataset", `${display(coverage.evaluated)}/${display(coverage.expected)} (${displayPercent(coverage.percent)})`],
        ["Taxa de sucesso", displayPercent(cards.success_rate)],
        ["Nota media geral", formatAverage(cards.average_score)],
        ["Spearman juiz x referencia", formatSpearman(cards.spearman_reference)],
        ["Consistencia juiz x arbitro", formatSpearman(cards.judge_arbiter_consistency)],
        ["Falhas criticas detectadas", cards.critical_failures],
        ["Divergencias para auditoria", cards.audit_divergences]
      ];
      for (const metric of metrics) {
        const card = document.createElement("div");
        card.className = "metric-card";
        const value = document.createElement("span");
        value.className = "metric-value";
        value.textContent = display(metric[1]);
        const label = document.createElement("span");
        label.className = "metric-label";
        label.textContent = metric[0];
        card.appendChild(value);
        card.appendChild(label);
        const source = metric[0].startsWith("Spearman") ? cards.spearman_reference : metric[0].startsWith("Consistencia") ? cards.judge_arbiter_consistency : null;
        if (source?.note) {
          const note = document.createElement("span");
          note.className = "metric-label";
          note.textContent = source.note;
          card.appendChild(note);
        }
        root.appendChild(card);
      }
    }

    function renderDashboardCases(cases) {
      const body = document.getElementById("dashboard-cases-body");
      body.textContent = "";
      if (!cases.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 9;
        cell.className = "muted";
        cell.textContent = "Sem casos criticos ou divergencias no filtro atual.";
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      cases.slice(0, 40).forEach((item) => {
        const row = document.createElement("tr");
        for (const value of [
          item.reason,
          item.dataset,
          item.answer_id,
          item.question_id,
          item.candidate_model,
          item.judge_model,
          normalizeRole(item.role),
          item.score,
          item.status
        ]) appendCell(row, display(value));
        body.appendChild(row);
      });
    }

    function displayPercent(value) {
      return value === null || value === undefined ? "-" : `${value}%`;
    }

    function formatSpearman(value) {
      if (!value || !value.available) return "N/A";
      return `${Number(value.value).toFixed(3)} (n=${value.sample_size})`;
    }

    function renderAuditLog(data) {
      const cell = document.getElementById("audit-log");
      const path = data.audit_log || data.result?.audit_log || "-";
      const auditLogUrl = data.audit_log_url;
      currentAuditLogUrl = auditLogUrl || null;
      cell.textContent = "";
      if (auditLogUrl) {
        const row = document.createElement("span");
        row.className = "audit-log-row";
        const link = document.createElement("a");
        link.href = auditLogUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = path;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "audit-log-button";
        button.title = "Abrir live audit log";
        button.setAttribute("aria-label", "Abrir live audit log");
        const icon = document.createElement("span");
        icon.className = "audit-log-button-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "▤";
        const label = document.createElement("span");
        label.textContent = "Live log";
        button.appendChild(icon);
        button.appendChild(label);
        button.onclick = openAuditLogDialog;
        row.appendChild(link);
        row.appendChild(button);
        cell.appendChild(row);
        if (document.getElementById("audit-log-dialog").open) loadCurrentAuditLog();
        return;
      }
      cell.textContent = path;
    }

    function openAuditLogDialog() {
      document.getElementById("audit-log-dialog").showModal();
      loadCurrentAuditLog();
    }

    async function loadCurrentAuditLog() {
      const liveLog = document.getElementById("audit-log-content");
      if (!liveLog || !currentAuditLogUrl) return;
      try {
        const response = await fetch(currentAuditLogUrl);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.detail || "Audit log ainda nao disponivel.");
        }
        liveLog.textContent = await response.text();
        liveLog.scrollTop = liveLog.scrollHeight;
      } catch (error) {
        liveLog.textContent = friendlyErrorMessage(error.message);
      }
    }

    function payload() {
      applyEndpointSources();
      return {
        panel_mode: value("panel_mode"),
        dataset: value("dataset"),
        batch_size: Number(value("batch_size")),
        judge_execution_strategy: value("judge_execution_strategy"),
        judge_model: value("judge_model"),
        secondary_judge_model: value("secondary_judge_model"),
        arbiter_judge_model: value("arbiter_judge_model"),
        always_run_arbiter: document.getElementById("always_run_arbiter").checked,
        remote_judge_base_url: value("remote_judge_base_url"),
        remote_judge_api_key: value("remote_judge_api_key"),
        remote_secondary_judge_base_url: value("remote_secondary_judge_base_url"),
        remote_secondary_judge_api_key: value("remote_secondary_judge_api_key"),
        remote_arbiter_judge_base_url: value("remote_arbiter_judge_base_url"),
        remote_arbiter_judge_api_key: value("remote_arbiter_judge_api_key"),
        judge_arbitration_min_delta: optionalNumber("judge_arbitration_min_delta"),
        remote_judge_timeout_seconds: optionalNumber("remote_judge_timeout_seconds"),
        remote_judge_temperature: optionalNumber("remote_judge_temperature"),
        remote_judge_max_tokens: optionalNumber("remote_judge_max_tokens"),
        remote_judge_top_p: optionalNumber("remote_judge_top_p"),
        remote_judge_openai_compatible: value("remote_judge_openai_compatible") === "true",
        judge_save_raw_response: document.getElementById("judge_save_raw_response").checked
      };
    }

    function optionalNumber(id) {
      const raw = value(id);
      return raw === "" ? null : Number(raw);
    }

    async function postJson(url, body, retryOnCsrf = true) {
      if (!csrfToken) await loadConfig();
      const response = await fetch(url, {
        method: "POST",
        headers: {"content-type": "application/json", "x-csrf-token": csrfToken},
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (response.status === 403 && data.detail === "Invalid CSRF token." && retryOnCsrf) {
        await loadConfig();
        return postJson(url, body, false);
      }
      if (!response.ok) throw new Error(data.detail || "Request failed");
      return data;
    }

    async function postBackupFile(file, retryOnCsrf = true) {
      if (!csrfToken) await loadConfig();
      const response = await fetch("/api/database-restore", {
        method: "POST",
        headers: {"content-type": "application/sql", "x-csrf-token": csrfToken, "x-backup-filename": file.name},
        body: await file.arrayBuffer()
      });
      const data = await response.json();
      if (response.status === 403 && data.detail === "Invalid CSRF token." && retryOnCsrf) {
        await loadConfig();
        return postBackupFile(file, false);
      }
      if (!response.ok) throw new Error(data.detail || "Request failed");
      return data;
    }

    function renderProgress(progress) {
      const pct = progress?.percent ?? 0;
      document.getElementById("batch-progress").value = pct;
      setText("progress-label", `${pct}% - ${progress?.current ?? 0}/${progress?.total ?? 0} respostas`);
    }

    function renderRun(data) {
      const status = data.status || "dry-run";
      setText("run-status", status);
      renderStatusIcon(status);
      updateStopButton(data.run_id, status);
      renderAuditLog(data);
      setText("command-preview", data.command_preview || data.result?.command_preview || "");
      renderProgress(data.progress);
      const eligibility = data.eligibility || data.result?.eligibility;
      setText("eligible-missing", eligibility?.missing);
      setText("eligible-failed", eligibility?.failed);
      setText("eligible-successful", eligibility?.successful);
      setText("eligible-will-process", eligibility?.will_process);
      const summary = data.result?.summary;
      setText("selected", summary?.selected_answers);
      setText("executed", summary?.executed_evaluations ?? data.progress?.executed_evaluations);
      setText("skipped", summary?.skipped_evaluations ?? data.progress?.skipped_evaluations);
      setText("arbiters", summary?.arbiter_evaluations ?? data.progress?.arbiter_evaluations);
      if (data.error) setText("output", friendlyErrorMessage(data.error));
      else if (data.result) setText("output", data.result.execution_summary);
      renderPostRunPanel(data);
      renderExecutionTable(data.evaluation_events || []);
    }

    function renderPostRunPanel(data) {
      const panel = document.getElementById("post-run-panel");
      const status = data.status || "dry-run";
      const shouldShow = ["completed", "failed", "cancelled"].includes(status) && Boolean(data.result);
      panel.hidden = !shouldShow;
      if (!shouldShow) return;
      const stats = buildPostRunStats(data);
      renderMetricCards(stats);
      renderBarChart("score-distribution-chart", stats.scoreDistribution, {scaleMax: 1, showPercent: true, colorByLabel: true});
      renderBarChart("judge-failures-chart", stats.failuresByJudge, {scaleMax: 1, showPercent: true, tone: "bad"});
      renderBarChart("arbitration-chart", stats.arbitrations, {scaleMax: 1, showPercent: true, tone: "arbiter"});
      renderBarChart("candidate-average-chart", stats.averageByCandidate, {scaleMax: 5});
      renderBarChart("judge-average-chart", stats.averageByJudge, {scaleMax: 5});
    }

    function buildPostRunStats(data) {
      const events = data.evaluation_events || [];
      const summary = data.result?.summary || {};
      const scoredEvents = events.filter((event) => event.status === "success" && Number.isFinite(Number(event.score)));
      const failedEvents = events.filter((event) => event.status === "failed");
      const successCount = events.filter((event) => event.status === "success").length;
      const scoreDistribution = [1, 2, 3, 4, 5].map((score) => ({
        label: String(score),
        value: scoredEvents.filter((event) => Number(event.score) === score).length
      }));
      const avgScore = average(scoredEvents.map((event) => Number(event.score)));
      return {
        selectedAnswers: summary.selected_answers ?? data.eligibility?.will_process ?? data.progress?.total ?? 0,
        judgeCalls: events.filter((event) => event.status !== "skipped").length || summary.executed_evaluations || 0,
        successCount,
        failedCount: failedEvents.length,
        arbiterCount: summary.arbiter_evaluations ?? data.progress?.arbiter_evaluations ?? 0,
        averageScore: avgScore,
        duration: data.duration || "-",
        scoreDistribution,
        failuresByJudge: countBy(failedEvents, (event) => event.judge_model || "sem juiz"),
        arbitrations: [
          {label: "acionadas", value: summary.arbiter_evaluations ?? data.progress?.arbiter_evaluations ?? 0},
          {label: "sem arbitro", value: Math.max(0, (summary.selected_answers ?? data.progress?.total ?? 0) - (summary.arbiter_evaluations ?? data.progress?.arbiter_evaluations ?? 0))}
        ],
        averageByCandidate: averageBy(scoredEvents, (event) => event.candidate_model || "sem modelo"),
        averageByJudge: averageBy(scoredEvents, (event) => event.judge_model || "sem juiz")
      };
    }

    function renderMetricCards(stats) {
      const root = document.getElementById("post-run-cards");
      root.textContent = "";
      for (const metric of [
        ["Respostas selecionadas", stats.selectedAnswers],
        ["Chamadas de juiz realizadas", stats.judgeCalls],
        ["Success", stats.successCount],
        ["Failed", stats.failedCount],
        ["Arbitragens acionadas", stats.arbiterCount],
        ["Nota media", formatAverage(stats.averageScore)],
        ["Tempo total", stats.duration]
      ]) {
        const card = document.createElement("div");
        card.className = "metric-card";
        const value = document.createElement("span");
        value.className = "metric-value";
        value.textContent = display(metric[1]);
        const label = document.createElement("span");
        label.className = "metric-label";
        label.textContent = metric[0];
        card.appendChild(value);
        card.appendChild(label);
        root.appendChild(card);
      }
    }

    function renderBarChart(id, rows, options = {}) {
      const root = document.getElementById(id);
      root.textContent = "";
      const values = rows || [];
      const total = values.reduce((sum, row) => sum + (Number(row.value) || 0), 0);
      const max = Math.max(options.scaleMax || 0, ...values.map((row) => Number(row.value) || 0));
      if (!values.length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "Sem dados.";
        root.appendChild(empty);
        return;
      }
      for (const row of values) {
        const value = Number(row.value) || 0;
        const line = document.createElement("div");
        line.className = "bar-row";
        const label = document.createElement("span");
        label.className = "bar-label";
        label.title = row.label;
        label.textContent = row.label;
        const track = document.createElement("span");
        track.className = "bar-track";
        const fill = document.createElement("span");
        fill.className = "bar-fill";
        if (value === 0) fill.classList.add("zero");
        applyBarTone(fill, row, options);
        const basis = options.showPercent ? total : max;
        fill.style.width = `${basis ? Math.round((value / basis) * 100) : 0}%`;
        track.appendChild(fill);
        const number = document.createElement("span");
        number.className = "bar-value";
        const count = document.createElement("span");
        count.className = `bar-count ${valueTone(value, row, options)}`;
        count.style.setProperty("--pill-pct", `${max ? Math.round((value / max) * 100) : 0}%`);
        count.textContent = Number.isInteger(value) ? String(value) : value.toFixed(1);
        number.appendChild(count);
        if (options.showPercent) {
          const percent = document.createElement("span");
          percent.className = "bar-percent";
          percent.textContent = `(${total ? Math.round((value / total) * 100) : 0}%)`;
          number.appendChild(percent);
        }
        line.appendChild(label);
        line.appendChild(track);
        line.appendChild(number);
        root.appendChild(line);
      }
    }

    function applyBarTone(fill, row, options) {
      if (options.colorByLabel && ["1", "2", "3", "4", "5"].includes(String(row.label))) {
        fill.classList.add(`score-${row.label}`);
        return;
      }
      if (options.tone === "bad") fill.classList.add("failed");
      else if (options.tone === "arbiter" && row.label === "acionadas") fill.classList.add("arbiter");
      else if (options.tone === "arbiter") fill.classList.add("none");
    }

    function valueTone(value, row, options) {
      if (!value) return "";
      if (options.tone === "bad") return "bad";
      if (options.tone === "arbiter" && row.label === "acionadas") return "warning";
      if (options.colorByLabel && Number(row.label) <= 2) return "bad";
      if (options.colorByLabel && Number(row.label) >= 4) return "positive";
      return "";
    }

    function countBy(events, keyFn) {
      const counts = new Map();
      for (const event of events) counts.set(keyFn(event), (counts.get(keyFn(event)) || 0) + 1);
      return Array.from(counts, ([label, value]) => ({label, value})).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
    }

    function averageBy(events, keyFn) {
      const groups = new Map();
      for (const event of events) {
        const key = keyFn(event);
        const current = groups.get(key) || {sum: 0, count: 0};
        current.sum += Number(event.score);
        current.count += 1;
        groups.set(key, current);
      }
      return Array.from(groups, ([label, value]) => ({label, value: value.sum / value.count})).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
    }

    function average(values) {
      if (!values.length) return null;
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    }

    function formatAverage(value) {
      return value === null || value === undefined ? "-" : value.toFixed(1);
    }

    function renderExecutionTable(events) {
      const body = document.getElementById("execution-table-body");
      body.textContent = "";
      if (!events.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 13;
        cell.className = "muted";
        cell.textContent = "Aguardando execucao.";
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      events.forEach((event, index) => {
        const row = document.createElement("tr");
        appendStatusCell(row, event.status);
        for (const value of [
          event.dataset,
          event.question_id,
          event.candidate_model,
          event.judge_model,
          normalizeRole(event.role),
          event.score,
          event.delta,
          formatBoolean(event.arbiter_triggered),
          event.trigger_reason,
          formatLatency(event.latency_ms),
          friendlyErrorMessage(event.error)
        ]) appendCell(row, display(value));
        const detailsCell = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "detail-button";
        button.textContent = "Detalhes";
        button.onclick = () => openDetails(event, index);
        detailsCell.appendChild(button);
        row.appendChild(detailsCell);
        body.appendChild(row);
      });
    }

    function appendCell(row, value) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }

    function appendStatusCell(row, status) {
      const cell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge ${status || ""}`;
      badge.textContent = status || "-";
      cell.appendChild(badge);
      row.appendChild(cell);
    }

    function normalizeRole(role) {
      if (role === "principal") return "primary";
      if (role === "controle") return "secondary";
      if (role === "arbitro") return "arbiter";
      return role;
    }

    function formatBoolean(value) {
      if (value === true) return "sim";
      if (value === false) return "nao";
      return "-";
    }

    function formatLatency(value) {
      return value === null || value === undefined ? "-" : `${value} ms`;
    }

    function openDetails(event, index) {
      setText("details-title", `Detalhes da avaliacao #${index + 1} - resposta ${event.answer_id || "-"}`);
      setText("details-prompt", event.prompt || "-");
      setText("details-response", event.raw_response || "-");
      setText("details-rationale", event.rationale || friendlyErrorMessage(event.error) || "-");
      document.getElementById("details-dialog").showModal();
    }

    function renderStatusIcon(status) {
      const icon = document.getElementById("run-status-icon");
      icon.className = "status-icon";
      if (["queued", "running", "cancelling"].includes(status)) {
        icon.textContent = "";
        icon.classList.add("spinner");
      } else if (status === "completed" || status === "dry-run") {
        icon.textContent = "✓";
        icon.classList.add("ok");
      } else if (status === "failed") {
        icon.textContent = "!";
        icon.classList.add("bad");
      } else {
        icon.textContent = "-";
      }
    }

    function updateStopButton(runId, status) {
      const button = document.getElementById("stop-run");
      const canStop = Boolean(runId) && ["queued", "running", "cancelling"].includes(status);
      button.disabled = !canStop || status === "cancelling";
      button.textContent = status === "cancelling" ? "Parando..." : "Parar";
      activeRunId = canStop ? runId : null;
    }

    async function poll(runId) {
      const data = await (await fetch(`/api/runs/${runId}`)).json();
      renderRun(data);
      if (["completed", "failed", "cancelled"].includes(data.status) && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        activeRunId = null;
      }
    }

    async function loadHistory() {
      const response = await fetch("/api/run-history");
      const data = await response.json();
      renderHistory(data);
      historyLoaded = true;
    }

    function renderHistory(rows) {
      const body = document.getElementById("history-table-body");
      body.textContent = "";
      if (!rows.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 10;
        cell.className = "muted";
        cell.textContent = "Nenhuma execucao encontrada.";
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      rows.forEach((entry) => {
        const row = document.createElement("tr");
        row.className = "history-row";
        row.onclick = () => openHistoryLog(entry);
        for (const value of [
          entry.run_id,
          formatDateTime(entry.timestamp),
          entry.mode,
          entry.dataset,
          entry.batch_size,
          entry.successes,
          entry.failures,
          entry.duration
        ]) appendCell(row, display(value));
        const logCell = document.createElement("td");
        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "detail-button";
        openButton.textContent = "Abrir";
        openButton.onclick = (event) => {
          event.stopPropagation();
          openHistoryLog(entry);
        };
        logCell.appendChild(openButton);
        row.appendChild(logCell);
        const exportCell = document.createElement("td");
        const links = document.createElement("span");
        links.className = "history-export-links";
        links.appendChild(historyExportLink("CSV", "/api/run-history/export.csv", "run-history.csv"));
        links.appendChild(historyExportLink("JSON", "/api/run-history/export.json", "run-history.json"));
        exportCell.appendChild(links);
        row.appendChild(exportCell);
        body.appendChild(row);
      });
    }

    function historyExportLink(label, href, filename) {
      const link = document.createElement("a");
      link.href = href;
      link.download = filename;
      link.textContent = label;
      return link;
    }

    async function openHistoryLog(entry) {
      setText("history-log-run-id", entry.run_id);
      setText("history-log-path", entry.log_path);
      setText("history-log-content", "Carregando log...");
      try {
        const response = await fetch(entry.log_url);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.detail || "Log nao encontrado.");
        }
        setText("history-log-content", await response.text());
      } catch (error) {
        setText("history-log-content", friendlyErrorMessage(error.message));
      }
    }

    function switchTab(targetId) {
      for (const button of document.querySelectorAll(".tab-button")) {
        const active = button.dataset.tab === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
      }
      for (const panel of document.querySelectorAll(".tab-panel")) {
        panel.hidden = panel.id !== targetId;
      }
      if (targetId === "dashboard-panel" && !dashboardLoaded) loadDashboard();
      if (targetId === "history-panel" && !historyLoaded) loadHistory();
    }

    async function loadConfig() {
      const config = await (await fetch("/api/config")).json();
      csrfToken = config.csrf_token;
      const defaults = config.defaults || {};
      for (const key of ["panel_mode", "dataset", "batch_size", "judge_execution_strategy", "judge_model", "secondary_judge_model", "arbiter_judge_model", "judge_arbitration_min_delta", "remote_judge_timeout_seconds", "remote_judge_temperature", "remote_judge_max_tokens", "remote_judge_top_p"]) {
        if (defaults[key] !== null && defaults[key] !== undefined) document.getElementById(key).value = defaults[key];
      }
      document.getElementById("always_run_arbiter").checked = Boolean(defaults.always_run_arbiter);
      document.getElementById("judge_save_raw_response").checked = Boolean(defaults.judge_save_raw_response);
      document.getElementById("remote_judge_openai_compatible").value = String(Boolean(defaults.remote_judge_openai_compatible));
      setText("config-status", config.configuration_error || `Endpoints: juiz 1 ${config.endpoints?.JUDGE?.host || "-"} / juiz 2 ${config.endpoints?.SECONDARY_JUDGE?.host || "-"}`);
      setText("command-preview", config.command_preview || "");
      const presetRoot = document.getElementById("presets");
      for (const preset of config.presets || []) {
        const btn = document.createElement("button");
        btn.className = "secondary";
        btn.textContent = preset.name;
        btn.onclick = () => {
          for (const [key, val] of Object.entries(preset)) {
            if (key === "name") continue;
            if (key === "always_run_arbiter") document.getElementById(key).checked = Boolean(val);
            else document.getElementById(key).value = val;
          }
        };
        presetRoot.appendChild(btn);
      }
      renderEndpointFields();
      document.getElementById("dry-run").disabled = false;
      document.getElementById("run").disabled = false;
      await loadDashboard();
    }

    function copyEndpointValues(source, target) {
      const sourcePrefix = source === "secondary" ? "remote_secondary_judge" : "remote_judge";
      const targetPrefix = target === "arbiter" ? "remote_arbiter_judge" : "remote_secondary_judge";
      document.getElementById(`${targetPrefix}_base_url`).value = document.getElementById(`${sourcePrefix}_base_url`).value;
      document.getElementById(`${targetPrefix}_api_key`).value = document.getElementById(`${sourcePrefix}_api_key`).value;
    }

    function clearEndpoint(target) {
      const prefix = target === "judge" ? "remote_judge" : `remote_${target}_judge`;
      document.getElementById(`${prefix}_base_url`).value = "";
      document.getElementById(`${prefix}_api_key`).value = "";
    }

    function renderEndpointFields() {
      for (const name of ["judge", "secondary", "arbiter"]) {
        document.getElementById(`endpoint_fields_${name}`).hidden = value(`endpoint_source_${name}`) !== "custom";
      }
    }

    function applyEndpointSources() {
      const secondarySource = value("endpoint_source_secondary");
      const arbiterSource = value("endpoint_source_arbiter");
      if (value("endpoint_source_judge") === "env") clearEndpoint("judge");
      if (secondarySource === "env") clearEndpoint("secondary");
      else if (secondarySource === "judge") copyEndpointValues("judge", "secondary");
      if (arbiterSource === "env") clearEndpoint("arbiter");
      else if (arbiterSource === "judge") copyEndpointValues("judge", "arbiter");
      else if (arbiterSource === "secondary") copyEndpointValues("secondary", "arbiter");
    }

    for (const id of ["endpoint_source_judge", "endpoint_source_secondary", "endpoint_source_arbiter"]) {
      document.getElementById(id).onchange = () => {
        applyEndpointSources();
        renderEndpointFields();
      };
    }

    for (const button of document.querySelectorAll("[data-toggle-secret]")) {
      button.onclick = () => {
        const input = document.getElementById(button.dataset.toggleSecret);
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        button.textContent = showing ? "◉" : "◎";
        button.setAttribute("aria-pressed", String(!showing));
      };
    }
    document.getElementById("details-close").onclick = () => document.getElementById("details-dialog").close();
    document.getElementById("audit-log-close").onclick = () => document.getElementById("audit-log-dialog").close();
    document.getElementById("database-dump-dialog-close").onclick = () => document.getElementById("database-dump-dialog").close();
    function showDatabaseDumpDialog(data) {
      setText("database-dump-filename", data.filename || "-");
      setText("database-dump-path", data.path || "-");
      setText("database-dump-size", `${Math.round((data.size_bytes || 0) / 1024)} KB`);
      document.getElementById("database-dump-dialog").showModal();
    }
    function confirmDatabaseClean() {
      const dialog = document.getElementById("database-clean-dialog");
      return new Promise((resolve) => {
        const cancel = document.getElementById("database-clean-cancel");
        const confirm = document.getElementById("database-clean-confirm");
        const backupConfirm = document.getElementById("database-clean-backup-confirm");
        let settled = false;
        const cleanup = (action) => {
          if (settled) return;
          settled = true;
          cancel.onclick = null;
          confirm.onclick = null;
          backupConfirm.onclick = null;
          dialog.oncancel = null;
          dialog.onclose = null;
          if (dialog.open) dialog.close();
          resolve(action);
        };
        cancel.onclick = () => cleanup("cancel");
        confirm.onclick = () => cleanup("clean");
        backupConfirm.onclick = () => cleanup("backup-clean");
        dialog.oncancel = (event) => {
          event.preventDefault();
          cleanup("cancel");
        };
        dialog.onclose = () => cleanup("cancel");
        dialog.showModal();
      });
    }
    for (const button of document.querySelectorAll(".tab-button")) {
      button.onclick = () => switchTab(button.dataset.tab);
    }
    document.getElementById("dashboard-refresh").onclick = loadDashboard;
    document.getElementById("dashboard-clear").onclick = () => {
      document.getElementById("dashboard_dataset").value = "J1";
      document.getElementById("dashboard_status").value = "all";
      document.getElementById("dashboard_group_by").value = "modelo";
      for (const id of ["dashboard_candidate_model", "dashboard_judge_model"]) {
        for (const option of document.getElementById(id).options) option.selected = false;
      }
      loadDashboard();
    };

    const databaseActionsToggle = document.getElementById("database-actions-toggle");
    const databaseActionsMenu = document.getElementById("database-actions-menu");
    function setDatabaseActionsMenu(open) {
      databaseActionsMenu.hidden = !open;
      databaseActionsToggle.setAttribute("aria-expanded", String(open));
    }
    databaseActionsToggle.onclick = (event) => {
      event.stopPropagation();
      setDatabaseActionsMenu(databaseActionsMenu.hidden);
    };
    databaseActionsMenu.onclick = (event) => event.stopPropagation();
    document.addEventListener("click", () => setDatabaseActionsMenu(false));

    document.getElementById("database-clean").onclick = async () => {
      setDatabaseActionsMenu(false);
      const cleanAction = await confirmDatabaseClean();
      if (cleanAction === "cancel") return;
      const button = document.getElementById("database-clean");
      const status = document.getElementById("database-dump-status");
      button.disabled = true;
      try {
        if (cleanAction === "backup-clean") {
          status.textContent = "Gerando dump antes de limpar...";
          const dumpData = await postJson("/api/database-dumps", {});
          showDatabaseDumpDialog(dumpData);
        }
        status.textContent = "Restaurando banco para o estado inicial...";
        const data = await postJson("/api/database-reset", {});
        status.textContent = data.message || "Banco restaurado para o estado inicial.";
        await loadDashboard();
      } catch (error) {
        status.textContent = friendlyErrorMessage(error.message);
      } finally {
        button.disabled = false;
      }
    };

    const restoreFileInput = document.getElementById("database-restore-file");
    document.getElementById("database-restore").onclick = () => {
      setDatabaseActionsMenu(false);
      restoreFileInput.value = "";
      restoreFileInput.click();
    };
    restoreFileInput.onchange = async () => {
      const file = restoreFileInput.files?.[0];
      if (!file) return;
      const button = document.getElementById("database-restore");
      const status = document.getElementById("database-dump-status");
      button.disabled = true;
      status.textContent = `Restaurando backup ${file.name}...`;
      try {
        const data = await postBackupFile(file);
        status.textContent = data.message || "Backup restaurado.";
        await loadDashboard();
      } catch (error) {
        status.textContent = friendlyErrorMessage(error.message);
      } finally {
        button.disabled = false;
      }
    };

    document.getElementById("database-dump").onclick = async () => {
      setDatabaseActionsMenu(false);
      const button = document.getElementById("database-dump");
      const status = document.getElementById("database-dump-status");
      button.disabled = true;
      status.textContent = "Gerando dump completo...";
      try {
        const data = await postJson("/api/database-dumps", {});
        status.textContent = "";
        showDatabaseDumpDialog(data);
      } catch (error) {
        status.textContent = friendlyErrorMessage(error.message);
      } finally {
        button.disabled = false;
      }
    };

    document.getElementById("dry-run").onclick = async () => {
      try {
        const data = await postJson("/api/runs/dry-run", payload());
        renderRun({status:"dry-run", result:data, progress:{percent:100,current:0,total:0}});
      } catch (error) {
        setText("run-status", "failed");
        setText("output", friendlyErrorMessage(error.message));
      }
    };
    document.getElementById("stop-run").onclick = async () => {
      if (!activeRunId) return;
      try {
        const data = await postJson(`/api/runs/${activeRunId}/cancel`, {});
        renderRun(data);
      } catch (error) {
        setText("output", friendlyErrorMessage(error.message));
      }
    };
    document.getElementById("run").onclick = async () => {
      try {
        const data = await postJson("/api/runs", payload());
        activeRunId = data.run_id;
        renderRun(data);
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(() => poll(data.run_id), 1000);
        await poll(data.run_id);
      } catch (error) {
        setText("run-status", "failed");
        setText("output", friendlyErrorMessage(error.message));
      }
    };
    loadConfig();
  </script>
</body>
</html>
"""


app = create_app()
