from __future__ import annotations

from typing import Any

import pytest

from atividade_2.config import load_settings
from atividade_2.judge_clients.remote_http import RemoteHttpJudgeClient, RemoteJudgeError


class FakeTransport:
    def __init__(self, status_code: int, response: dict[str, Any]) -> None:
        self.status_code = status_code
        self.response = response
        self.payload: dict[str, Any] | None = None
        self.headers: dict[str, str] | None = None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> tuple[int, dict[str, Any]]:
        self.payload = payload
        self.headers = headers
        return self.status_code, self.response


def test_remote_client_sends_effective_model() -> None:
    settings = load_settings(
        dotenv_path=None,
        env={
            "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
            "REMOTE_JUDGE_API_KEY": "secret",
        },
    )
    transport = FakeTransport(
        200,
        {"choices": [{"message": {"content": '{"score": 5, "rationale": "ok"}'}}]},
    )
    client = RemoteHttpJudgeClient(settings, transport=transport)

    response = client.judge("prompt", "provider/model")

    assert response.text == '{"score": 5, "rationale": "ok"}'
    assert transport.payload is not None
    assert transport.payload["model"] == "provider/model"
    assert transport.headers is not None
    assert transport.headers["Authorization"] == "Bearer secret"
    assert transport.headers["User-Agent"] == "atividade-2-judge/0.1"


def test_remote_client_handles_non_2xx() -> None:
    settings = load_settings(
        dotenv_path=None,
        env={
            "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
            "REMOTE_JUDGE_API_KEY": "secret",
        },
    )
    client = RemoteHttpJudgeClient(settings, transport=FakeTransport(500, {"error": "down"}))

    with pytest.raises(RemoteJudgeError, match="HTTP 500"):
        client.judge("prompt", "provider/model")


def test_remote_client_requires_text_in_response() -> None:
    settings = load_settings(
        dotenv_path=None,
        env={
            "REMOTE_JUDGE_BASE_URL": "https://example.invalid/v1",
            "REMOTE_JUDGE_API_KEY": "secret",
        },
    )
    client = RemoteHttpJudgeClient(settings, transport=FakeTransport(200, {"choices": [{}]}))

    with pytest.raises(RemoteJudgeError, match="model text"):
        client.judge("prompt", "provider/model")
