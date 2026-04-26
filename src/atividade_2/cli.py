"""Command-line entry point for the Atividade 2 package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser without executing application logic."""
    return argparse.ArgumentParser(
        prog="atividade-2",
        description="Reusable command-line entry point for Atividade 2.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
