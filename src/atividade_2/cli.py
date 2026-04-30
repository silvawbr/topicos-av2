"""Command-line entry point for the Atividade 2 package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .audit import AuditLogger
from .config import ConfigurationError, load_settings, resolve_runtime_config
from .contracts import RuntimeJudgeConfig
from .db import connect
from .judge_clients.remote_http import RemoteHttpJudgeClient, RemoteJudgeError
from .model_aliases import format_model_mapping
from .parser import JudgeParseError
from .pipeline import JudgePipeline
from .repositories import JudgeRepository


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser without executing application logic."""
    parser = argparse.ArgumentParser(
        prog="atividade-2",
        description="Reusable command-line entry point for Atividade 2.",
    )
    subparsers = parser.add_subparsers(dest="command")
    run_judge = subparsers.add_parser(
        "run-judge",
        help="Run the local LLM-as-a-Judge pipeline with a remote HTTP model endpoint.",
    )
    run_judge.add_argument("--judge-provider", choices=["remote_http"])
    run_judge.add_argument("--panel-mode", choices=["single", "primary_only", "2plus1"])
    run_judge.add_argument("--judge-model", help="Single judge alias or provider model id.")
    run_judge.add_argument(
        "--primary-judge-panel",
        help="Comma-separated primary judge aliases or provider model ids.",
    )
    run_judge.add_argument("--arbiter-judge-model", help="Arbiter alias or provider model id.")
    run_judge.add_argument(
        "--always-run-arbiter",
        action="store_true",
        help="Run the arbiter for every answer in 2plus1 mode.",
    )
    run_judge.add_argument(
        "--judge-execution-strategy",
        choices=["sequential", "parallel"],
        help="Run judge API calls sequentially or in parallel within each answer.",
    )
    run_judge.add_argument(
        "--dataset",
        choices=["J1", "J2", "OAB_Bench", "OAB_Exames"],
        default="J2",
        help="Dataset to evaluate. J2 maps to OAB_Exames; J1 maps to OAB_Bench.",
    )
    run_judge.add_argument(
        "--limit",
        type=_positive_int,
        default=10,
        help="Maximum candidate answers to evaluate.",
    )
    run_judge.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve configuration and print the execution summary without DB or HTTP calls.",
    )
    run_judge.add_argument(
        "--audit-log",
        help="Path for detailed audit log. Defaults to outputs/audit/judge_run_<timestamp>.log.",
    )
    run_judge.add_argument(
        "--no-audit-animation",
        action="store_true",
        help="Disable animated terminal dots for long-running audit steps.",
    )
    run_judge.set_defaults(handler=run_judge_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        return 0
    try:
        return handler(args)
    except (ConfigurationError, RemoteJudgeError, JudgeParseError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")


def run_judge_command(args: argparse.Namespace) -> int:
    """Run or dry-run the judge pipeline."""
    audit_path = _resolve_audit_path(args.audit_log)
    animate = False if args.no_audit_animation else None
    with AuditLogger(file_path=audit_path, animate=animate) as audit:
        with audit.step("Loading configuration"):
            settings = load_settings()
        with audit.step(
            "Resolving judge mode and models",
            detail=(
                f"panel_mode_cli={args.panel_mode} judge_model_cli={_present(args.judge_model)} "
                f"primary_panel_cli={_present(args.primary_judge_panel)} "
                f"arbiter_cli={_present(args.arbiter_judge_model)} "
                f"execution_strategy_cli={_present(args.judge_execution_strategy)}"
            ),
        ):
            runtime_config = resolve_runtime_config(
                settings,
                judge_provider=args.judge_provider,
                panel_mode=args.panel_mode,
                judge_model=args.judge_model,
                primary_judge_panel=args.primary_judge_panel,
                arbiter_judge_model=args.arbiter_judge_model,
                always_run_arbiter=args.always_run_arbiter,
                execution_strategy=args.judge_execution_strategy,
            )
        summary_text = format_execution_summary(runtime_config)
        print(summary_text)
        print(f"Audit log: {audit.file_path}")
        audit.file_event("execution_summary", summary_text.replace("\n", " | "))
        if args.dry_run:
            audit.terminal_event("Dry run: no database rows selected and no remote judge calls made.")
            audit.file_event("dry_run_finished", "no database rows selected and no remote judge calls made")
            return 0

        with audit.step("Connecting to local PostgreSQL", detail="DATABASE_URL=<redacted>"):
            connection = connect(settings.database_url)
        try:
            repository = JudgeRepository(connection)
            with audit.step("Ensuring judge metadata schema"):
                repository.ensure_schema()
            with audit.step(
                f"Selecting candidate answers for {args.dataset}",
                detail=f"dataset={args.dataset} limit={args.limit}",
            ):
                answers = repository.select_candidate_answers(dataset=args.dataset, limit=args.limit)
            audit.file_event("answers_selected", f"count={len(answers)}")
            client = RemoteHttpJudgeClient(settings)
            with audit.step(
                "Running judge pipeline",
                detail=f"answers={len(answers)} mode={runtime_config.panel_mode}",
            ):
                summary = JudgePipeline(repository, client, audit=audit).run(answers, runtime_config)
        finally:
            with audit.step("Closing PostgreSQL connection"):
                connection.close()

        print()
        print("Execution result:")
        print(f"Selected answers: {summary.selected_answers}")
        print(f"Executed evaluations: {summary.executed_evaluations}")
        print(f"Skipped existing evaluations: {summary.skipped_evaluations}")
        print(f"Arbiter evaluations: {summary.arbiter_evaluations}")
        audit.file_event(
            "execution_result",
            (
                f"selected={summary.selected_answers} executed={summary.executed_evaluations} "
                f"skipped={summary.skipped_evaluations} arbiters={summary.arbiter_evaluations}"
            ),
        )
    return 0


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
                format_model_mapping(config.single_judge),
                f"Model source: {config.model_source}",
            ]
        )
        return "\n".join(lines)

    lines.append("Primary judges:")
    lines.extend(format_model_mapping(model) for model in config.primary_panel)
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
            format_model_mapping(config.arbiter),
            f"Arbitration min delta: {config.arbitration_min_delta}",
            f"Always run arbiter: {str(config.always_run_arbiter).lower()}",
            f"Model source: {config.model_source}",
        ]
    )
    return "\n".join(lines)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def _resolve_audit_path(raw_path: str | None) -> Path:
    if raw_path:
        return Path(raw_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("outputs") / "audit" / f"judge_run_{timestamp}.log"


def _present(value: str | None) -> str:
    return "provided" if value else "not_provided"


if __name__ == "__main__":
    raise SystemExit(main())
