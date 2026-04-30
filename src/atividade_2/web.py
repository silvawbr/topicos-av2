"""Local FastAPI console for running the AV2 judge pipeline."""

from __future__ import annotations

import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .config import ConfigurationError
from .contracts import BatchProgress, EligibilitySummary, PipelineSummary
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
    progress: BatchProgress = field(default_factory=lambda: _initial_progress())
    result: RunJudgeResult | None = None
    error: str | None = None
    audit_log: str | None = None
    command_preview: str | None = None
    eligibility: EligibilitySummary | None = None


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

        def update_eligibility(eligibility: EligibilitySummary) -> None:
            with self._lock:
                self._jobs[run_id].eligibility = eligibility

        try:
            result = self.service.run(
                job.request,
                progress_callback=update_progress,
                eligibility_callback=update_eligibility,
            )
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
                job.eligibility = result.eligibility
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
        "audit_log_url": f"/api/runs/{job.run_id}/audit-log" if job.audit_log else None,
        "command_preview": job.command_preview,
        "eligibility": asdict(job.eligibility) if job.eligibility is not None else None,
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
    main { max-width:1180px; margin:0 auto; padding:20px; display:grid; grid-template-columns: 380px 1fr; gap:18px; }
    section, aside { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; }
    aside { padding-bottom:82px; }
    h2 { font-size:15px; margin:0 0 12px; }
    label { display:grid; gap:5px; margin:10px 0; color:var(--muted); font-size:12px; }
    input, select { width:100%; min-height:36px; border:1px solid var(--line); border-radius:6px; padding:7px 9px; font:inherit; color:var(--ink); background:#fff; }
    button { border:1px solid var(--accent); background:var(--accent); color:#fff; border-radius:6px; min-height:36px; padding:0 12px; font-weight:650; cursor:pointer; }
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
    </section>
  </main>
  <script>
    let csrfToken = "";
    let pollTimer = null;

    function value(id) { return document.getElementById(id).value; }
    function setText(id, text) { document.getElementById(id).textContent = text ?? "-"; }

    function renderAuditLog(data) {
      const cell = document.getElementById("audit-log");
      const path = data.audit_log || data.result?.audit_log || "-";
      cell.textContent = "";
      if (data.audit_log_url) {
        const link = document.createElement("a");
        link.href = data.audit_log_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = path;
        cell.appendChild(link);
        return;
      }
      cell.textContent = path;
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
      const status = data.status || "dry-run";
      setText("run-status", status);
      renderStatusIcon(status);
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
      if (data.error) setText("output", data.error);
      else if (data.result) setText("output", data.result.execution_summary);
    }

    function renderStatusIcon(status) {
      const icon = document.getElementById("run-status-icon");
      icon.className = "status-icon";
      if (["queued", "running"].includes(status)) {
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
