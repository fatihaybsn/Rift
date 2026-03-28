"""Tests for run/read report API surfaces."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db import AnalysisRun, DeterministicFinding, MigrationTask, get_db_session
from app.main import create_app


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class FakeReadSession:
    """Minimal session stub for run/report read endpoint tests."""

    def __init__(
        self,
        *,
        run: AnalysisRun | None,
        findings: list[DeterministicFinding] | None = None,
        migration_tasks: list[MigrationTask] | None = None,
    ) -> None:
        self.run = run
        self.findings = findings or []
        self.migration_tasks = migration_tasks or []

    def get(self, model: type[object], key: object) -> AnalysisRun | None:
        if model is AnalysisRun and self.run is not None and key == self.run.id:
            return self.run
        return None

    def execute(self, statement: Any) -> _FakeExecuteResult:
        entity = statement.column_descriptions[0].get("entity")
        if entity is DeterministicFinding:
            rows = sorted(self.findings, key=lambda item: (item.finding_order, item.finding_key))
            return _FakeExecuteResult(rows)
        if entity is MigrationTask:
            rows = sorted(
                self.migration_tasks,
                key=lambda item: (item.priority, item.created_at, item.id),
            )
            return _FakeExecuteResult(rows)
        msg = f"Unexpected query entity in fake session: {entity!r}"
        raise AssertionError(msg)


def _build_client_with_fake_session(fake_session: FakeReadSession) -> TestClient:
    app = create_app()

    def override_get_db_session():
        yield fake_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app)


def _build_sample_run(*, run_id: uuid.UUID, status: str) -> AnalysisRun:
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    return AnalysisRun(
        id=run_id,
        status=status,
        attempt_count=1,
        created_at=now,
        updated_at=now,
        processing_started_at=now,
        completed_at=now if status == "completed" else None,
        failed_at=now if status == "failed" else None,
        failure_stage="parse_spec_old" if status == "failed" else None,
        error_code="openapi_parse_error" if status == "failed" else None,
        failure_reason="invalid JSON input" if status == "failed" else None,
    )


def _build_sample_findings(run_id: uuid.UUID) -> list[DeterministicFinding]:
    return [
        DeterministicFinding(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            run_id=run_id,
            finding_key="000001:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            finding_order=1,
            category="operation_surface",
            location="operation:/pets#get",
            http_method="get",
            severity="high",
            title="Method removed",
            detail="Endpoint removal is a breaking API surface change.",
            metadata_json={"code": "method_removed", "compatibility": "breaking"},
        ),
        DeterministicFinding(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            run_id=run_id,
            finding_key="000002:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            finding_order=2,
            category="parameter",
            location="parameter:/pets#get#limit",
            http_method="get",
            severity="low",
            title="Parameter added",
            detail="New optional request parameter.",
            metadata_json={"code": "parameter_added", "compatibility": "non_breaking"},
        ),
        DeterministicFinding(
            id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            run_id=run_id,
            finding_key="000003:cccccccccccccccccccccccccccccccc",
            finding_order=3,
            category="request",
            location="request:/pets#post",
            http_method="post",
            severity="high",
            title="Request body required changed",
            detail="A required request field was added.",
            metadata_json={"code": "request_body_required_changed", "compatibility": "breaking"},
        ),
    ]


def _build_sample_task(run_id: uuid.UUID) -> MigrationTask:
    now = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    return MigrationTask(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        run_id=run_id,
        finding_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        source="manual",
        status="proposed",
        title="Update client request builder",
        detail="Ensure removed method is no longer called.",
        priority=1,
        created_at=now,
        updated_at=now,
    )


def test_get_run_returns_persisted_lifecycle_state() -> None:
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    fake_session = FakeReadSession(run=_build_sample_run(run_id=run_id, status="failed"))

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["status"] == "failed"
    assert body["attempt_count"] == 1
    assert body["failure_stage"] == "parse_spec_old"
    assert body["error_code"] == "openapi_parse_error"
    assert body["failure_reason"] == "invalid JSON input"


def test_get_run_returns_404_for_unknown_id() -> None:
    run_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    fake_session = FakeReadSession(run=None)

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/runs/{run_id}")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_get_run_rejects_invalid_uuid() -> None:
    fake_session = FakeReadSession(run=None)

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/runs/not-a-uuid")

    assert response.status_code == 422


def test_get_report_json_returns_stable_grouped_shape() -> None:
    run_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    fake_session = FakeReadSession(
        run=_build_sample_run(run_id=run_id, status="completed"),
        findings=_build_sample_findings(run_id),
        migration_tasks=[],
    )

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["report_id"] == str(run_id)
    assert body["run_id"] == str(run_id)
    assert body["status"] == "completed"
    assert body["summary_counts"] == {
        "total_findings": 3,
        "findings_by_category": [
            {"category": "operation_surface", "count": 1},
            {"category": "parameter", "count": 1},
            {"category": "request", "count": 1},
        ],
    }
    assert body["severity_breakdown"] == {"high": 2, "medium": 0, "low": 1}
    assert [item["severity"] for item in body["findings_grouped"]] == [
        "high",
        "low",
    ]
    assert [item["category"] for item in body["findings_grouped"][0]["categories"]] == [
        "operation_surface",
        "request",
    ]
    assert body["findings_grouped"][0]["categories"][0]["items"][0]["code"] == "method_removed"
    assert (
        body["findings_grouped"][0]["categories"][1]["items"][0]["code"]
        == "request_body_required_changed"
    )
    assert body["findings_grouped"][1]["categories"][0]["items"][0]["code"] == "parameter_added"
    assert body["changelog_tasks"]["items"] == []


def test_get_report_returns_404_for_unknown_id() -> None:
    run_id = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    fake_session = FakeReadSession(run=None)

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_get_report_rejects_invalid_format_query() -> None:
    run_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    fake_session = FakeReadSession(run=_build_sample_run(run_id=run_id, status="completed"))

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}?format=html")

    assert response.status_code == 422


def test_get_report_markdown_snapshot_output() -> None:
    run_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    fake_session = FakeReadSession(
        run=_build_sample_run(run_id=run_id, status="completed"),
        findings=[_build_sample_findings(run_id)[0], _build_sample_findings(run_id)[2]],
        migration_tasks=[_build_sample_task(run_id)],
    )

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}?format=markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")

    expected = "\n".join(
        [
            "# API Change Radar Report",
            "",
            f"- Report ID: `{run_id}`",
            f"- Run ID: `{run_id}`",
            "- Status: `completed`",
            "- Created At: `2026-03-20T12:00:00+00:00`",
            "- Updated At: `2026-03-20T12:00:00+00:00`",
            "",
            "## Summary Counts",
            "- Total findings: 2",
            "- High: 2",
            "- Medium: 0",
            "- Low: 0",
            "",
            "## Findings Grouped by Severity and Category",
            "",
            "### HIGH (2)",
            "#### operation_surface (1)",
            "1. **[HIGH]** `method_removed` at `operation:/pets#get`",
            "   - Key: `000001:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`",
            "   - Method: `get`",
            "   - Compatibility: `breaking`",
            "   - Title: Method removed",
            "   - Detail: Endpoint removal is a breaking API surface change.",
            "#### request (1)",
            "1. **[HIGH]** `request_body_required_changed` at `request:/pets#post`",
            "   - Key: `000003:cccccccccccccccccccccccccccccccc`",
            "   - Method: `post`",
            "   - Compatibility: `breaking`",
            "   - Title: Request body required changed",
            "   - Detail: A required request field was added.",
            "",
            "## Changelog-derived Tasks (Placeholder)",
            (
                "Placeholder section for changelog-derived tasks. "
                "Deterministic findings remain authoritative."
            ),
            "1. [priority=1] Update client request builder (source=manual, status=proposed)",
            "   - Task ID: `33333333-3333-3333-3333-333333333333`",
            "   - Related finding: `11111111-1111-1111-1111-111111111111`",
            "   - Detail: Ensure removed method is no longer called.",
        ]
    )
    assert response.text == expected


def test_get_report_demo_returns_minimal_html_summary_links_and_top_high() -> None:
    run_id = uuid.UUID("12121212-1212-1212-1212-121212121212")
    fake_session = FakeReadSession(
        run=_build_sample_run(run_id=run_id, status="completed"),
        findings=_build_sample_findings(run_id),
        migration_tasks=[],
    )

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "<h1>API Change Radar Report Demo</h1>" in body
    assert "<h2>Summary Counts</h2>" in body
    assert "<li>Total findings: 3</li>" in body
    assert "<li>High: 2</li>" in body
    assert "<li>Medium: 0</li>" in body
    assert "<li>Low: 1</li>" in body
    assert "<h2>Top High-Severity Findings</h2>" in body
    assert body.count("<ol>") == 1
    assert "Method removed" in body
    assert "Request body required changed" in body
    assert "Parameter added" not in body
    assert f'<a href="../{run_id}">JSON</a>' in body
    assert f'<a href="../{run_id}?format=markdown">Markdown</a>' in body


def test_get_report_demo_escapes_dynamic_content() -> None:
    run_id = uuid.UUID("13131313-1313-1313-1313-131313131313")
    run = _build_sample_run(run_id=run_id, status="completed")
    finding = DeterministicFinding(
        id=uuid.UUID("14141414-1414-1414-1414-141414141414"),
        run_id=run_id,
        finding_key="000001:dddddddddddddddddddddddddddddddd",
        finding_order=1,
        category="operation_surface",
        location='operation:/pets?<script>alert("x")</script>#get',
        http_method='g<et&"',
        severity="high",
        title='<b>Method removed</b>',
        detail='Detail with <img src=x onerror=alert(1)>',
        metadata_json={"code": '<code&"', "compatibility": "breaking"},
    )
    fake_session = FakeReadSession(run=run, findings=[finding], migration_tasks=[])

    with _build_client_with_fake_session(fake_session) as client:
        response = client.get(f"{Settings().api_prefix}/reports/{run_id}/demo")

    assert response.status_code == 200
    body = response.text
    assert "<script>" not in body
    assert "<img src=x onerror=alert(1)>" not in body
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in body
    assert "&lt;b&gt;Method removed&lt;/b&gt;" in body
    assert "g&lt;et&amp;&quot;" in body
    assert "&lt;code&amp;&quot;" in body
