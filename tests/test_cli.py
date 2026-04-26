"""Tests for the command-line interface baseline."""

from __future__ import annotations

import pytest

from atividade_2 import cli


def test_cli_help_exits_successfully() -> None:
    """The CLI help command should be available through argparse."""
    with pytest.raises(SystemExit) as exit_error:
        cli.main(["--help"])

    assert exit_error.value.code == 0
