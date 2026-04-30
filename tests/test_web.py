from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from atividade_2.contracts import BatchProgress, EligibilitySummary, EvaluationProgress, PipelineSummary
from atividade_2.run_judge_service import RunJudgeResult
from atividade_2.web import create_app


class FakeRunJudgeService:
    def __init__(self, audit_path: str = "outputs/audit/test.log") -> None:
        self.requests = []
        self.audit_path = audit_path

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
            audit_path=Path(self.audit_path),
            command_preview=".venv/bin/python -m atividade_2.cli run-judge --dataset J2",
        )

    def run(
        self,
        request,
        *,
        progress_callback=None,
        on_resolved=None,
        eligibility_callback=None,
        evaluation_callback=None,
    ):
        self.requests.append(request)
        eligibility = EligibilitySummary(missing=83, failed=7, successful=240, batch_size=1, will_process=1)
        if eligibility_callback is not None and not request.dry_run:
            eligibility_callback(eligibility)
        if evaluation_callback is not None and not request.dry_run:
            base_event = {
                "dataset": "J2",
                "question_id": 10,
                "answer_id": 20,
                "candidate_model": "modelo-candidato",
                "judge_model": "openai/gpt-oss-120b",
                "role": "principal",
                "panel_mode": "single",
                "trigger_reason": "single:single_mode",
            }
            evaluation_callback(
                EvaluationProgress(
                    status="running",
                    **base_event,
                    prompt="prompt usado",
                )
            )
            evaluation_callback(
                EvaluationProgress(
                    status="success",
                    **base_event,
                    score=5,
                    arbiter_triggered=None,
                    latency_ms=123,
                    prompt="prompt usado",
                    raw_response='{"score":5}',
                    rationale="justificativa curta",
                )
            )
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
            audit_log=self.audit_path,
            execution_summary="Judge mode: single",
            command_preview=".venv/bin/python -m atividade_2.cli run-judge --dataset J2",
            batch_size=1,
            eligibility=None if request.dry_run else eligibility,
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

    def run(
        self,
        request,
        *,
        progress_callback=None,
        on_resolved=None,
        eligibility_callback=None,
        evaluation_callback=None,
    ):
        self.started.set()
        self.release.wait(timeout=2)
        return super().run(
            request,
            progress_callback=progress_callback,
            on_resolved=on_resolved,
            eligibility_callback=eligibility_callback,
            evaluation_callback=evaluation_callback,
        )


def test_web_index_contains_progress_element() -> None:
    client = TestClient(create_app(FakeRunJudgeService()))

    response = client.get("/")

    assert response.status_code == 200
    assert '<progress id="batch-progress"' in response.text
    assert 'id="eligible-missing"' in response.text
    assert 'id="execution-table-body"' in response.text
    assert "/api/runs/" in response.text
    assert "Execucoes anteriores" in response.text
    assert 'id="history-table-body"' in response.text
    assert 'id="history-log-content"' in response.text


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
    assert data["eligibility"]["missing"] == 83
    assert data["eligibility"]["failed"] == 7
    assert data["eligibility"]["successful"] == 240
    assert data["eligibility"]["will_process"] == 1
    assert data["result"]["summary"]["executed_evaluations"] == 1
    assert len(data["evaluation_events"]) == 1
    assert data["evaluation_events"][0]["status"] == "success"
    assert data["evaluation_events"][0]["question_id"] == 10
    assert data["evaluation_events"][0]["candidate_model"] == "modelo-candidato"
    assert data["evaluation_events"][0]["latency_ms"] == 123


def test_run_exposes_audit_log_link_and_file_content(tmp_path) -> None:
    audit_path = tmp_path / "judge.log"
    audit_path.write_text("audit content\n", encoding="utf-8")
    client = TestClient(create_app(FakeRunJudgeService(str(audit_path))))
    token = client.get("/api/config").json()["csrf_token"]

    created = client.post(
        "/api/runs",
        headers={"x-csrf-token": token},
        json={"panel_mode": "single", "dataset": "J2", "batch_size": 1},
    )

    data = created.json()
    assert data["audit_log"] == str(audit_path)
    assert data["audit_log_url"] == f"/api/runs/{data['run_id']}/audit-log"
    log_response = client.get(data["audit_log_url"])
    assert log_response.status_code == 200
    assert log_response.text == "audit content\n"


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


def test_run_history_lists_audit_logs_with_metadata(tmp_path) -> None:
    _write_audit_log(
        tmp_path / "judge_run_20260430_104512.log",
        """
2026-04-30T13:45:12+00:00 | audit_log_started | path=outputs/audit/judge_run_20260430_104512.log
2026-04-30T13:45:12+00:00 | execution_summary | Judge provider: remote_http | Judge mode: 2plus1 | Judge execution strategy: sequential
2026-04-30T13:45:12+00:00 | command_preview | .venv/bin/python -m atividade_2.cli run-judge --panel-mode 2plus1 --dataset J2 --batch-size 10 --judge-execution-strategy sequential
2026-04-30T13:45:20+00:00 | evaluation_parsed | answer_id=1 status=failed
2026-04-30T13:49:24+00:00 | execution_result | selected=10 executed=8 skipped=0 arbiters=1
2026-04-30T13:49:24+00:00 | audit_log_finished
""",
    )
    _write_audit_log(
        tmp_path / "judge_run_20260430_120000.log",
        """
2026-04-30T15:00:00+00:00 | audit_log_started | path=outputs/audit/judge_run_20260430_120000.log
2026-04-30T15:00:00+00:00 | execution_summary | Judge provider: remote_http | Judge mode: single | Judge execution strategy: parallel
2026-04-30T15:00:00+00:00 | command_preview | .venv/bin/python -m atividade_2.cli run-judge --panel-mode single --dataset J1 --batch-size 1 --judge-execution-strategy parallel
2026-04-30T15:00:07+00:00 | execution_result | selected=1 executed=1 skipped=0 arbiters=0
2026-04-30T15:00:07+00:00 | audit_log_finished
""",
    )
    client = TestClient(create_app(FakeRunJudgeService(), audit_dir=tmp_path))

    response = client.get("/api/run-history")

    assert response.status_code == 200
    data = response.json()
    assert [row["run_id"] for row in data] == ["judge_run_20260430_120000", "judge_run_20260430_104512"]
    older = data[1]
    assert older["timestamp"] == "2026-04-30T13:45:12+00:00"
    assert older["mode"] == "2plus1"
    assert older["dataset"] == "J2"
    assert older["batch_size"] == 10
    assert older["successes"] == 8
    assert older["failures"] == 1
    assert older["duration"] == "4min12s"
    assert older["log_url"] == "/api/run-history/judge_run_20260430_104512/audit-log"


def test_run_history_log_endpoint_returns_file_content(tmp_path) -> None:
    log_path = tmp_path / "judge_run_20260430_104512.log"
    _write_audit_log(log_path, "2026-04-30T13:45:12+00:00 | audit_log_started\n")
    client = TestClient(create_app(FakeRunJudgeService(), audit_dir=tmp_path))

    response = client.get("/api/run-history/judge_run_20260430_104512/audit-log")

    assert response.status_code == 200
    assert response.text == "2026-04-30T13:45:12+00:00 | audit_log_started\n"


def test_run_history_exports_csv_and_json(tmp_path) -> None:
    _write_audit_log(
        tmp_path / "judge_run_20260430_104512.log",
        """
2026-04-30T13:45:12+00:00 | audit_log_started
2026-04-30T13:45:12+00:00 | execution_summary | Judge mode: single
2026-04-30T13:45:12+00:00 | command_preview | .venv/bin/python -m atividade_2.cli run-judge --dataset J2 --batch-size 3
2026-04-30T13:45:13+00:00 | execution_result | selected=3 executed=3 skipped=0 arbiters=0
""",
    )
    client = TestClient(create_app(FakeRunJudgeService(), audit_dir=tmp_path))

    json_response = client.get("/api/run-history/export.json")
    csv_response = client.get("/api/run-history/export.csv")

    assert json_response.status_code == 200
    assert json_response.json()[0]["run_id"] == "judge_run_20260430_104512"
    assert csv_response.status_code == 200
    assert csv_response.text.splitlines()[0] == (
        "run_id,timestamp,mode,dataset,batch_size,successes,failures,duration,log_path"
    )
    assert "judge_run_20260430_104512,2026-04-30T13:45:12+00:00,single,J2,3,3,0,1s," in csv_response.text


def test_run_history_rejects_path_traversal(tmp_path) -> None:
    client = TestClient(create_app(FakeRunJudgeService(), audit_dir=tmp_path))

    response = client.get("/api/run-history/../secret/audit-log")

    assert response.status_code in {400, 404}


def _write_audit_log(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")
