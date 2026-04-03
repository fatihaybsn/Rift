"""One end-to-end smoke path: run creation -> processing -> report retrieval."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.db import get_db_session
from app.main import create_app
from app.services.run_orchestration import RunOrchestrationService
from tests.fixtures.sample_specs import build_valid_spec_json


def _multipart_specs():
    return [
        (
            "specs",
            (
                "old.json",
                build_valid_spec_json(title="Old API", include_patch=False),
                "application/json",
            ),
        ),
        (
            "specs",
            (
                "new.json",
                build_valid_spec_json(title="New API", include_patch=True),
                "application/json",
            ),
        ),
    ]


def test_full_stack_smoke_run_to_report(integration_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.runs.process_analysis_in_background", lambda run_id: None)
    app = create_app()
    session = integration_db()

    def override_get_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with TestClient(app) as client:
            create_response = client.post(
                f"{Settings().api_prefix}/runs",
                files=_multipart_specs(),
                data={"changelog_text": "Patch endpoint added."},
            )

            assert create_response.status_code == 201
            run_id = create_response.json()["run_id"]

            run = RunOrchestrationService().process_run(db=session, run_id=run_id)
            assert run.status == "completed"

            run_response = client.get(f"{Settings().api_prefix}/runs/{run_id}")
            assert run_response.status_code == 200
            assert run_response.json()["status"] == "completed"
            assert run_response.json()["llm_status"] == "disabled"

            report_response = client.get(f"{Settings().api_prefix}/reports/{run_id}")
            assert report_response.status_code == 200
            report_payload = report_response.json()
            assert report_payload["run_id"] == run_id
            assert report_payload["status"] == "completed"
            assert report_payload["summary_counts"]["total_findings"] >= 1
            assert report_payload["llm"]["status"] == "disabled"

            markdown_response = client.get(
                f"{Settings().api_prefix}/reports/{run_id}?format=markdown"
            )
            assert markdown_response.status_code == 200
            assert "# API Change Radar Report" in markdown_response.text

            demo_response = client.get(f"{Settings().api_prefix}/reports/{run_id}/demo")
            assert demo_response.status_code == 200
            assert "API Change Radar Report Demo" in demo_response.text
    finally:
        session.close()
