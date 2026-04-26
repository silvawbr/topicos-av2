"""Tests for baseline package and contracts imports."""

from __future__ import annotations

import atividade_2
from atividade_2 import contracts


def test_package_can_be_imported() -> None:
    """The installed package should expose a version string."""
    assert isinstance(atividade_2.__version__, str)


def test_contracts_module_can_be_imported() -> None:
    """The contracts module should exist without fake domain models."""
    assert contracts.__doc__
