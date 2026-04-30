"""PostgreSQL connection helpers."""

from __future__ import annotations

from typing import Any


def connect(database_url: str) -> Any:
    """Create a psycopg2 connection from ``DATABASE_URL``.

    psycopg2 is imported lazily so pure unit tests do not need a local database.
    """
    try:
        import psycopg2
    except ImportError as error:
        raise RuntimeError(
            "psycopg2-binary is required for database access. "
            "Run .venv/bin/python -m pip install -e '.[dev]'."
        ) from error
    return psycopg2.connect(database_url)
