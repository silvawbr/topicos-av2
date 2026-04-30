from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from atividade_2.contracts import BatchProgress, PipelineSummary
from atividade_2.run_judge_service import RunJudgeResult
from atividade_2.web import create_app


class FakeRunJudgeService:
    def __init__(self) -> None:
        self.requests = []

    def describe_config(self) -> dict:
        return {
            "defaults": {
                "panel_mode": "single",
                "dataset": "J2",
                "batch_size": 1,
                "judge_execution_strategy": "sequential",
                "judge_model": "gpt-oss-120b",
                "secondary_judge_model": "llama-3.3-70b-instruct",
                "arbiter_judge_model": "m-prometheus-14b",
                "always_run_arbiter": False,
                "judge_arbitration_min_delta": 2,
                "remote_judge_timeout_seconds": 180,
                "remote_judge_temperature": 0.0,
                "remote_judge_max_tokens": 4000,
                "remote_judge_top_p": 1.0,
                "remote_judge_openai_compatible": True,
                "judge_save_raw_response": True,
            },
            "endpoints": {"JUDGE": {"host": "example.invalid", "has_api_key": True}},
            "presets": [],
            "command_preview": ".venv/bin/python -m atividade_2.cli run-judge --dry-run",
        }

    def resolve(self, request):
        return SimpleNamespace(
            audit_path=Path("outputs/audit/test.log"),
            command_preview=".venv/bin/python -m atividade_2.cli run-judge --dataset J2",
        )

    def run(self, request, *, progress_callback=None, on_resolved=None):
        self.requests.append(request)
        if progress_callback is not None:
            progress_callback(
                BatchProgress(
                    current=1,
                    total=1,
                    percent=100,
                    executed_evaluations=1,
                    skipped_evaluations=0,
                    arbiter_evaluations=0,
                )
            )
        return RunJudgeResult(
            dry_run=request.dry_run,
            audit_log="outputs/audit/test.log",
            execution_summary="Judge mode: single",
            command_preview=".venv/bin/python -m atividade_2.cli run-judge --dataset J2",
            batch_size=1,
            summary=None
            if request.dry_run
            else PipelineSummary(
                selected_answers=1,
                executed_evaluations=1,
                skipped_evaluations=0,
                arbiter_evaluations=0,
            ),
        )


class BlockingRunJudgeService(FakeRunJudgeService):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, request, *, progress_callback=None, on_resolved=None):
        self.started.set()
        self.release.wait(timeout=2)
        return super().run(request, progress_callback=progress_callback, on_resolved=on_resolved)


def test_web_index_contains_progress_element() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))

    response = client.get("/")

    assert response.status_code == 200
    assert '<progress id="batch-progress"' in response.text
    assert "/api/runs/" in response.text


def test_web_index_contains_endpoint_and_advanced_controls() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="remote_judge_base_url"' in response.text
    assert 'id="remote_judge_api_key" type="password"' in response.text
    assert 'data-toggle-secret="remote_judge_api_key"' in response.text
    assert 'data-toggle-secret="remote_secondary_judge_api_key"' in response.text
    assert 'data-toggle-secret="remote_arbiter_judge_api_key"' in response.text
    assert 'id="endpoint_source_judge"' in response.text
    assert 'id="endpoint_source_secondary"' in response.text
    assert 'id="endpoint_source_arbiter"' in response.text
    assert 'id="endpoint_fields_judge" class="endpoint-fields" hidden' in response.text
    assert 'id="endpoint_fields_secondary" class="endpoint-fields" hidden' in response.text
    assert 'id="endpoint_fields_arbiter" class="endpoint-fields" hidden' in response.text
    assert 'id="remote_judge_timeout_seconds"' in response.text
    assert 'id="remote_judge_openai_compatible"' in response.text
    assert "<summary>Campos avancados</summary>" in response.text
    assert 'id="always_run_arbiter"' in response.text
    assert '<button id="run">Executar</button>' in response.text
    assert 'id="run-status-icon"' in response.text


def test_config_endpoint_is_secret_safe_and_returns_csrf_token() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))

    response = client.get("/api/config")

    assert response.status_code == 200
    data = response.json()
    assert data["csrf_token"]
    assert data["endpoints"]["JUDGE"]["host"] == "example.invalid"
    assert "secret" not in response.text.lower()


def test_mutating_endpoint_requires_csrf_token() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))

    response = client.post("/api/runs/dry-run", json={"panel_mode": "single"})

    assert response.status_code == 403


def test_dry_run_returns_secret_safe_preview() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))
    token = client.get("/api/config").json()["csrf_token"]

    response = client.post(
        "/api/runs/dry-run",
        headers={"x-csrf-token": token},
        json={"panel_mode": "single", "dataset": "J2", "batch_size": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["summary"] is None
    assert "Judge mode: single" in data["execution_summary"]
    assert "secret" not in response.text.lower()


def test_dry_run_accepts_endpoint_and_advanced_overrides() -> None:
    service = FakeRunJudgeService()
    client = TestClient(create_app(service))
    token = client.get("/api/config").json()["csrf_token"]

    response = client.post(
        "/api/runs/dry-run",
        headers={"x-csrf-token": token},
        json={
            "panel_mode": "2plus1",
            "dataset": "J2",
            "batch_size": 3,
            "remote_judge_base_url": "https://judge1.example.invalid/v1",
            "remote_judge_api_key": "key-1",
            "remote_secondary_judge_base_url": "https://judge2.example.invalid/v1",
            "remote_secondary_judge_api_key": "key-2",
            "remote_arbiter_judge_base_url": "https://arbiter.example.invalid/v1",
            "remote_arbiter_judge_api_key": "key-3",
            "judge_arbitration_min_delta": 1,
            "remote_judge_timeout_seconds": 240,
            "remote_judge_temperature": 0.0,
            "remote_judge_max_tokens": 4000,
            "remote_judge_top_p": 1.0,
            "remote_judge_openai_compatible": True,
            "judge_save_raw_response": False,
        },
    )

    assert response.status_code == 200
    request = service.requests[-1]
    assert request.remote_judge_base_url == "https://judge1.example.invalid/v1"
    assert request.remote_secondary_judge_api_key == "key-2"
    assert request.remote_arbiter_judge_base_url == "https://arbiter.example.invalid/v1"
    assert request.judge_arbitration_min_delta == 1
    assert request.remote_judge_timeout_seconds == 240
    assert request.judge_save_raw_response is False


def test_run_lifecycle_exposes_batch_progress() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))
    token = client.get("/api/config").json()["csrf_token"]

    created = client.post(
        "/api/runs",
        headers={"x-csrf-token": token},
        json={"panel_mode": "single", "dataset": "J2", "batch_size": 1},
    )

    assert created.status_code == 200
    run_id = created.json()["run_id"]
    current = client.get(f"/api/runs/{run_id}")

    assert current.status_code == 200
    data = current.json()
    assert data["progress"]["percent"] == 100
    assert data["result"]["summary"]["executed_evaluations"] == 1


def test_second_run_is_rejected_while_one_is_active() -> None:
    service = BlockingRunJudgeService()
    client = TestClient(create_app(service))
    token = client.get("/api/config").json()["csrf_token"]

    first = client.post(
        "/api/runs",
        headers={"x-csrf-token": token},
        json={"panel_mode": "single", "dataset": "J2", "batch_size": 1},
    )
    assert first.status_code == 200
    assert service.started.wait(timeout=1)

    second = client.post(
        "/api/runs",
        headers={"x-csrf-token": token},
        json={"panel_mode": "single", "dataset": "J2", "batch_size": 1},
    )
    service.release.set()

    assert second.status_code == 409
