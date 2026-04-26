"""Project setup smoke tests."""

from __future__ import annotations


def test_package_importable() -> None:
    """The package should be importable after editable install."""
    import atividade_2

    assert atividade_2 is not None
