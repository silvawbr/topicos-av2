"""Shared application service for CLI and local Web judge runs."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import AuditLogger
from .config import ConfigurationError, load_settings, resolve_runtime_config
from .contracts import (
    BatchProgress,
    JudgeSettings,
    ModelSpec,
    PipelineSummary,
    RuntimeJudgeConfig,
    StoredJudgeRole,
)
from .db import connect
from .judge_clients.remote_http import RemoteHttpJudgeClient
from .model_aliases import format_model_mapping
from .pipeline import JudgePipeline
from .repositories import JudgeRepository


@dataclass(frozen=True)
class RunJudgeRequest:
    """User-provided run options before env/default resolution."""

    judge_provider: str | None = None
    panel_mode: str | None = None
    judge_model: str | None = None
    secondary_judge_model: str | None = None
    arbiter_judge_model: str | None = None
    always_run_arbiter: bool = False
    judge_execution_strategy: str | None = None
    dataset: str = "J2"
    batch_size: int | None = None
    dry_run: bool = False
    audit_log: str | None = None
    no_audit_animation: bool = False


@dataclass(frozen=True)
class ResolvedRun:
    """Effective run config after settings and overrides are resolved."""

    runtime_config: RuntimeJudgeConfig
    batch_size: int
    audit_path: Path
    execution_summary: str
    command_preview: str


@dataclass(frozen=True)
class RunJudgeResult:
    """Structured result for CLI and Web adapters."""

    dry_run: bool
    audit_log: str
    execution_summary: str
    command_preview: str
    batch_size: int
    summary: PipelineSummary | None = None


class RunJudgeService:
    """Application boundary for running the judge pipeline without subprocesses."""

    def __init__(
        self,
        *,
        settings_loader: Callable[[], JudgeSettings] = load_settings,
        connect_func: Callable[[str], Any] = connect,
        repository_factory: Callable[[Any], JudgeRepository] = JudgeRepository,
        client_factory: Callable[[JudgeSettings], RemoteHttpJudgeClient] = RemoteHttpJudgeClient,
    ) -> None:
        self._settings_loader = settings_loader
        self._connect = connect_func
        self._repository_factory = repository_factory
        self._client_factory = client_factory

    def describe_config(self) -> dict[str, Any]:
        """Return secret-safe defaults and effective configuration for the Web UI."""
        settings = self._settings_loader()
        base = {
            "defaults": {
                "panel_mode": settings.judge_panel_mode,
                "dataset": "J2",
                "batch_size": settings.judge_batch_size,
                "judge_execution_strategy": settings.judge_execution_strategy,
                "judge_model": settings.remote_judge_default_model,
                "secondary_judge_model": settings.remote_secondary_judge_model,
                "arbiter_judge_model": settings.remote_arbiter_judge_model,
                "always_run_arbiter": settings.judge_always_run_arbiter,
            },
            "supported": {
                "panel_modes": ["single", "primary_only", "2plus1"],
                "datasets": ["J1", "J2"],
                "judge_execution_strategies": ["sequential", "parallel"],
            },
            "endpoints": _endpoint_overview(settings),
            "presets": [
                {"name": "Smoke J2", "panel_mode": "single", "dataset": "J2", "batch_size": 1},
                {"name": "Smoke J1", "panel_mode": "single", "dataset": "J1", "batch_size": 1},
                {"name": "Comparacao primaria", "panel_mode": "primary_only"},
                {"name": "AV2 principal", "panel_mode": "2plus1"},
                {"name": "Auditoria completa", "panel_mode": "2plus1", "always_run_arbiter": True},
            ],
        }
        try:
            resolved = self.resolve(RunJudgeRequest())
        except ConfigurationError as error:
            base["configuration_error"] = str(error)
            return base
        base["execution_summary"] = resolved.execution_summary
        base["command_preview"] = resolved.command_preview
        return base

    def resolve(self, request: RunJudgeRequest) -> ResolvedRun:
        """Resolve settings and CLI/Web overrides without touching DB or remote HTTP."""
        settings = self._settings_loader()
        runtime_config = resolve_runtime_config(
            settings,
            judge_provider=request.judge_provider,
            panel_mode=request.panel_mode,
            judge_model=request.judge_model,
            secondary_judge_model=request.secondary_judge_model,
            arbiter_judge_model=request.arbiter_judge_model,
            always_run_arbiter=request.always_run_arbiter,
            execution_strategy=request.judge_execution_strategy,
        )
        batch_size = request.batch_size or settings.judge_batch_size
        execution_summary = format_execution_summary(runtime_config)
        return ResolvedRun(
            runtime_config=runtime_config,
            batch_size=batch_size,
            audit_path=_resolve_audit_path(request.audit_log),
            execution_summary=execution_summary,
            command_preview=build_command_preview(request, runtime_config, batch_size),
        )

    def run(
        self,
        request: RunJudgeRequest,
        *,
        on_resolved: Callable[[ResolvedRun], None] | None = None,
        progress_callback: Callable[[BatchProgress], None] | None = None,
    ) -> RunJudgeResult:
        """Run or dry-run the judge pipeline."""
        audit_path = _resolve_audit_path(request.audit_log)
        animate = False if request.no_audit_animation else None
        with AuditLogger(file_path=audit_path, animate=animate) as audit:
            with audit.step("Loading configuration"):
                settings = self._settings_loader()
            with audit.step(
                "Resolving judge mode and models",
                detail=(
                    f"panel_mode_cli={_present(request.panel_mode)} judge_model_cli={_present(request.judge_model)} "
                    f"secondary_judge_cli={_present(request.secondary_judge_model)} "
                    f"arbiter_cli={_present(request.arbiter_judge_model)} "
                    f"execution_strategy_cli={_present(request.judge_execution_strategy)}"
                ),
            ):
                runtime_config = resolve_runtime_config(
                    settings,
                    judge_provider=request.judge_provider,
                    panel_mode=request.panel_mode,
                    judge_model=request.judge_model,
                    secondary_judge_model=request.secondary_judge_model,
                    arbiter_judge_model=request.arbiter_judge_model,
                    always_run_arbiter=request.always_run_arbiter,
                    execution_strategy=request.judge_execution_strategy,
                )
            resolved = ResolvedRun(
                runtime_config=runtime_config,
                batch_size=request.batch_size or settings.judge_batch_size,
                audit_path=audit_path,
                execution_summary=format_execution_summary(runtime_config),
                command_preview=build_command_preview(request, runtime_config, request.batch_size or settings.judge_batch_size),
            )
            if on_resolved is not None:
                on_resolved(resolved)
            audit.file_event("execution_summary", resolved.execution_summary.replace("\n", " | "))
            audit.file_event("command_preview", resolved.command_preview)
            if request.dry_run:
                audit.terminal_event("Dry run: no database rows selected and no remote judge calls made.")
                audit.file_event("dry_run_finished", "no database rows selected and no remote judge calls made")
                return _result(request, resolved, None)

            with audit.step("Connecting to local PostgreSQL", detail="DATABASE_URL=<redacted>"):
                connection = self._connect(settings.database_url)
            try:
                repository = self._repository_factory(connection)
                with audit.step("Ensuring judge metadata schema"):
                    repository.ensure_schema()
                with audit.step(
                    f"Selecting pending candidate answers for {request.dataset}",
                    detail=f"dataset={request.dataset} batch_size={resolved.batch_size}",
                ):
                    answers = repository.select_pending_candidate_answers(
                        dataset=request.dataset,
                        batch_size=resolved.batch_size,
                        required_evaluations=_required_evaluations(runtime_config),
                    )
                audit.file_event("answers_selected", f"count={len(answers)}")
                client = self._client_factory(settings)
                with audit.step(
                    "Running judge pipeline",
                    detail=f"answers={len(answers)} mode={runtime_config.panel_mode}",
                ):
                    summary = JudgePipeline(
                        repository,
                        client,
                        audit=audit,
                        progress_callback=progress_callback,
                    ).run(answers, runtime_config)
            finally:
                with audit.step("Closing PostgreSQL connection"):
                    connection.close()

            audit.file_event(
                "execution_result",
                (
                    f"selected={summary.selected_answers} executed={summary.executed_evaluations} "
                    f"skipped={summary.skipped_evaluations} arbiters={summary.arbiter_evaluations}"
                ),
            )
            return _result(request, resolved, summary)


def format_execution_summary(config: RuntimeJudgeConfig) -> str:
    """Build a secret-safe execution summary."""
    lines = [
        f"Judge provider: {config.provider}",
        f"Judge mode: {config.panel_mode}",
        f"Judge execution strategy: {config.execution_strategy}",
    ]
    if config.panel_mode == "single":
        assert config.single_judge is not None
        lines.extend(
            [
                "Judge model:",
                _format_model_with_endpoint(config, config.single_judge, "SINGLE"),
                f"Model source: {config.model_source}",
            ]
        )
        return "\n".join(lines)

    lines.append("Primary judges:")
    lines.extend(
        _format_model_with_endpoint(config, model, endpoint_key)
        for model, endpoint_key in zip(config.primary_panel, ("JUDGE", "SECONDARY_JUDGE"), strict=True)
    )
    if config.panel_mode == "primary_only":
        lines.extend(
            [
                "Arbiter: disabled for primary_only mode",
                f"Model source: {config.model_source}",
            ]
        )
        return "\n".join(lines)

    assert config.arbiter is not None
    lines.extend(
        [
            "Arbiter:",
            _format_model_with_endpoint(config, config.arbiter, "ARBITER"),
            f"Arbitration min delta: {config.arbitration_min_delta}",
            f"Always run arbiter: {str(config.always_run_arbiter).lower()}",
            f"Model source: {config.model_source}",
        ]
    )
    return "\n".join(lines)


def build_command_preview(request: RunJudgeRequest, config: RuntimeJudgeConfig, batch_size: int) -> str:
    """Build the equivalent CLI command without secrets."""
    args = [
        ".venv/bin/python",
        "-m",
        "atividade_2.cli",
        "run-judge",
        "--panel-mode",
        config.panel_mode,
        "--dataset",
        request.dataset,
        "--batch-size",
        str(batch_size),
        "--judge-execution-strategy",
        config.execution_strategy,
    ]
    if config.panel_mode == "single":
        assert config.single_judge is not None
        args.extend(["--judge-model", config.single_judge.requested])
    else:
        if config.primary_panel:
            args.extend(["--judge-model", config.primary_panel[0].requested])
        if len(config.primary_panel) > 1:
            args.extend(["--secondary-judge-model", config.primary_panel[1].requested])
        if config.arbiter is not None:
            args.extend(["--arbiter-judge-model", config.arbiter.requested])
    if config.always_run_arbiter:
        args.append("--always-run-arbiter")
    if request.dry_run:
        args.append("--dry-run")
    return shlex.join(args)


def _result(
    request: RunJudgeRequest,
    resolved: ResolvedRun,
    summary: PipelineSummary | None,
) -> RunJudgeResult:
    return RunJudgeResult(
        dry_run=request.dry_run,
        audit_log=str(resolved.audit_path),
        execution_summary=resolved.execution_summary,
        command_preview=resolved.command_preview,
        batch_size=resolved.batch_size,
        summary=summary,
    )


def _required_evaluations(config: RuntimeJudgeConfig) -> tuple[tuple[ModelSpec, StoredJudgeRole, str], ...]:
    if config.panel_mode == "single":
        assert config.single_judge is not None
        return ((config.single_judge, "principal", config.panel_mode),)
    return tuple(
        (model, role, config.panel_mode)
        for model, role in zip(config.primary_panel, ("principal", "controle"), strict=False)
    )


def _format_model_with_endpoint(config: RuntimeJudgeConfig, model: ModelSpec, endpoint_key: str) -> str:
    mapping = format_model_mapping(model)
    endpoint = _resolve_endpoint_base_url(config, model, endpoint_key)
    host = _endpoint_host(endpoint)
    return f"{mapping} | endpoint={host}"


def _resolve_endpoint_base_url(config: RuntimeJudgeConfig, model: ModelSpec, endpoint_key: str) -> str | None:
    normalized_endpoint_key = _endpoint_key(endpoint_key)
    if normalized_endpoint_key == "JUDGE":
        return config.settings.remote_judge_base_url
    endpoint = config.settings.remote_judge_endpoints.get(normalized_endpoint_key)
    if endpoint is not None:
        return endpoint.base_url
    for candidate in (model.requested, model.provider_model):
        for key in _endpoint_keys(candidate):
            endpoint = config.settings.remote_judge_endpoints.get(key)
            if endpoint is not None:
                return endpoint.base_url
    return config.settings.remote_judge_base_url


def _endpoint_overview(settings: JudgeSettings) -> dict[str, dict[str, Any]]:
    return {
        "JUDGE": {
            "host": _endpoint_host(settings.remote_judge_base_url),
            "has_api_key": bool(settings.remote_judge_api_key),
        },
        "SECONDARY_JUDGE": {
            "host": _endpoint_host(
                settings.remote_judge_endpoints.get("SECONDARY_JUDGE").base_url
                if settings.remote_judge_endpoints.get("SECONDARY_JUDGE")
                else settings.remote_judge_base_url
            ),
            "has_api_key": bool(
                settings.remote_judge_endpoints.get("SECONDARY_JUDGE")
                or settings.remote_judge_api_key
            ),
        },
        "ARBITER": {
            "host": _endpoint_host(
                settings.remote_judge_endpoints.get("ARBITER").base_url
                if settings.remote_judge_endpoints.get("ARBITER")
                else settings.remote_judge_base_url
            ),
            "has_api_key": bool(settings.remote_judge_endpoints.get("ARBITER") or settings.remote_judge_api_key),
        },
    }


def _endpoint_keys(model: str) -> tuple[str, ...]:
    keys = [_endpoint_key(model)]
    if "/" in model:
        keys.append(_endpoint_key(model.rsplit("/", 1)[-1]))
    return tuple(dict.fromkeys(key for key in keys if key))


def _endpoint_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _endpoint_host(base_url: str | None) -> str:
    if not base_url:
        return "<missing>"
    host = urlparse(base_url).hostname
    return host or "<invalid>"


def _resolve_audit_path(raw_path: str | None) -> Path:
    if raw_path:
        return Path(raw_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("outputs") / "audit" / f"judge_run_{timestamp}.log"


def _present(value: str | None) -> str:
    return "provided" if value else "not_provided"
