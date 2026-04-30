"""Judge client protocol."""

from __future__ import annotations

from typing import Protocol

from atividade_2.contracts import JudgeRawResponse


class JudgeClient(Protocol):
    """Provider-agnostic judge execution boundary."""

    def judge(
        self,
        prompt: str,
        model: str,
        *,
        requested_model: str | None = None,
        endpoint_key: str | None = None,
    ) -> JudgeRawResponse:
        """Execute a judge prompt with the resolved provider model id."""
