"""Local FastAPI console for running the AV2 judge pipeline."""

from __future__ import annotations

import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import ConfigurationError
from .contracts import BatchProgress, PipelineSummary
from .judge_clients.remote_http import RemoteJudgeError
from .parser import JudgeParseError
from .run_judge_service import RunJudgeRequest, RunJudgeResult, RunJudgeService


RunStatus = Literal["queued", "running", "completed", "failed"]


class RunPayload(BaseModel):
    panel_mode: Literal["single", "primary_only", "2plus1"] | None = None
    dataset: Literal["J1", "J2", "OAB_Bench", "OAB_Exames"] = "J2"
    batch_size: int | None = Field(default=None, ge=1)
    judge_execution_strategy: Literal["sequential", "parallel"] | None = None
    judge_model: str | None = None
    secondary_judge_model: str | None = None
    arbiter_judge_model: str | None = None
    always_run_arbiter: bool = False

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
            dry_run=dry_run,
            no_audit_animation=True,
        )


@dataclass
class JobState:
    run_id: str
    status: RunStatus
    request: RunJudgeRequest
    progress: BatchProgress = field(default_factory=lambda: _initial_progress())
    result: RunJudgeResult | None = None
    error: str | None = None
    audit_log: str | None = None
    command_preview: str | None = None


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

    def _run(self, run_id: str) -> None:
        with self._lock:
            job = self._jobs[run_id]
            job.status = "running"

        def update_progress(progress: BatchProgress) -> None:
            with self._lock:
                self._jobs[run_id].progress = progress

        try:
            result = self.service.run(job.request, progress_callback=update_progress)
        except (ConfigurationError, RemoteJudgeError, JudgeParseError, RuntimeError, ValueError) as error:
            with self._lock:
                job = self._jobs[run_id]
                job.status = "failed"
                job.error = str(error)
        else:
            with self._lock:
                job = self._jobs[run_id]
                job.status = "completed"
                job.result = result
                job.audit_log = result.audit_log
                job.command_preview = result.command_preview
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None


def create_app(service: RunJudgeService | None = None) -> FastAPI:
    app = FastAPI(title="Atividade 2 Judge Console")
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.jobs = JobRegistry(service or RunJudgeService())

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    @app.get("/api/config")
    def get_config(request: Request) -> dict:
        config = request.app.state.jobs.service.describe_config()
        config["csrf_token"] = request.app.state.csrf_token
        return config

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

    return app


def _require_csrf(request: Request) -> None:
    token = request.headers.get("x-csrf-token")
    if not token or token != request.app.state.csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _serialize_job(job: JobState) -> dict:
    return {
        "run_id": job.run_id,
        "status": job.status,
        "progress": asdict(job.progress),
        "audit_log": job.audit_log,
        "command_preview": job.command_preview,
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
        "summary": _serialize_summary(result.summary),
    }


def _serialize_summary(summary: PipelineSummary | None) -> dict | None:
    if summary is None:
        return None
    return asdict(summary)


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
    :root { color-scheme: light; --ink:#18212f; --muted:#5b6472; --line:#d8dde6; --bg:#f6f7f9; --accent:#1769aa; --ok:#1d7f4e; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 28px 12px; border-bottom:1px solid var(--line); background:#fff; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    main { max-width:1180px; margin:0 auto; padding:20px; display:grid; grid-template-columns: 380px 1fr; gap:18px; }
    section, aside { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; }
    h2 { font-size:15px; margin:0 0 12px; }
    label { display:grid; gap:5px; margin:10px 0; color:var(--muted); font-size:12px; }
    input, select { width:100%; min-height:36px; border:1px solid var(--line); border-radius:6px; padding:7px 9px; font:inherit; color:var(--ink); background:#fff; }
    button { border:1px solid var(--accent); background:var(--accent); color:#fff; border-radius:6px; min-height:36px; padding:0 12px; font-weight:650; cursor:pointer; }
    button.secondary { color:var(--accent); background:#fff; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .presets { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }
    .presets button { min-height:32px; font-size:12px; }
    .status { font-size:13px; color:var(--muted); }
    pre { overflow:auto; background:#101828; color:#f9fafb; border-radius:6px; padding:12px; min-height:76px; white-space:pre-wrap; }
    progress { width:100%; height:22px; accent-color:var(--accent); }
    table { width:100%; border-collapse:collapse; margin-top:12px; font-size:13px; }
    th, td { text-align:left; border-bottom:1px solid var(--line); padding:8px; }
    .ok { color:var(--ok); }
    .bad { color:var(--bad); }
    .muted { color:var(--muted); }
    @media (max-width: 860px) { main { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>Atividade 2 Judge Console</h1>
    <div id="config-status" class="status">Carregando configuracao local...</div>
  </header>
  <main>
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
      <label>Juiz 1
        <input id="judge_model" autocomplete="off">
      </label>
      <label>Juiz 2
        <input id="secondary_judge_model" autocomplete="off">
      </label>
      <label>Arbitro
        <input id="arbiter_judge_model" autocomplete="off">
      </label>
      <label>
        <span><input id="always_run_arbiter" type="checkbox" style="width:auto; min-height:auto"> Always run arbiter</span>
      </label>
      <div class="actions">
        <button class="secondary" id="dry-run">Validar configuracao</button>
        <button id="run">Executar</button>
      </div>
    </aside>
    <section>
      <h2>Execucao</h2>
      <progress id="batch-progress" max="100" value="0"></progress>
      <div id="progress-label" class="status">0% - aguardando execucao</div>
      <table>
        <tbody>
          <tr><th>Status</th><td id="run-status">idle</td></tr>
          <tr><th>Audit log</th><td id="audit-log" class="muted">-</td></tr>
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
    </section>
  </main>
  <script>
    let csrfToken = "";
    let pollTimer = null;

    function value(id) { return document.getElementById(id).value; }
    function setText(id, text) { document.getElementById(id).textContent = text ?? "-"; }

    function payload() {
      return {
        panel_mode: value("panel_mode"),
        dataset: value("dataset"),
        batch_size: Number(value("batch_size")),
        judge_execution_strategy: value("judge_execution_strategy"),
        judge_model: value("judge_model"),
        secondary_judge_model: value("secondary_judge_model"),
        arbiter_judge_model: value("arbiter_judge_model"),
        always_run_arbiter: document.getElementById("always_run_arbiter").checked
      };
    }

    async function postJson(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: {"content-type": "application/json", "x-csrf-token": csrfToken},
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Request failed");
      return data;
    }

    function renderProgress(progress) {
      const pct = progress?.percent ?? 0;
      document.getElementById("batch-progress").value = pct;
      setText("progress-label", `${pct}% - ${progress?.current ?? 0}/${progress?.total ?? 0} respostas`);
    }

    function renderRun(data) {
      setText("run-status", data.status || "dry-run");
      setText("audit-log", data.audit_log || data.result?.audit_log || "-");
      setText("command-preview", data.command_preview || data.result?.command_preview || "");
      renderProgress(data.progress);
      const summary = data.result?.summary;
      setText("selected", summary?.selected_answers);
      setText("executed", summary?.executed_evaluations ?? data.progress?.executed_evaluations);
      setText("skipped", summary?.skipped_evaluations ?? data.progress?.skipped_evaluations);
      setText("arbiters", summary?.arbiter_evaluations ?? data.progress?.arbiter_evaluations);
      if (data.error) setText("output", data.error);
      else if (data.result) setText("output", data.result.execution_summary);
    }

    async function poll(runId) {
      const data = await (await fetch(`/api/runs/${runId}`)).json();
      renderRun(data);
      if (["completed", "failed"].includes(data.status) && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    async function loadConfig() {
      const config = await (await fetch("/api/config")).json();
      csrfToken = config.csrf_token;
      const defaults = config.defaults || {};
      for (const key of ["panel_mode", "dataset", "batch_size", "judge_execution_strategy", "judge_model", "secondary_judge_model", "arbiter_judge_model"]) {
        if (defaults[key] !== null && defaults[key] !== undefined) document.getElementById(key).value = defaults[key];
      }
      document.getElementById("always_run_arbiter").checked = Boolean(defaults.always_run_arbiter);
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
    }

    document.getElementById("dry-run").onclick = async () => {
      try {
        const data = await postJson("/api/runs/dry-run", payload());
        renderRun({status:"dry-run", result:data, progress:{percent:100,current:0,total:0}});
      } catch (error) {
        setText("run-status", "failed");
        setText("output", error.message);
      }
    };
    document.getElementById("run").onclick = async () => {
      try {
        const data = await postJson("/api/runs", payload());
        renderRun(data);
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(() => poll(data.run_id), 1000);
        await poll(data.run_id);
      } catch (error) {
        setText("run-status", "failed");
        setText("output", error.message);
      }
    };
    loadConfig();
  </script>
</body>
</html>
"""


app = create_app()
