"""Integration tests for report retrieval against real persisted runs."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import (
    AnalysisRun,
    ArtifactKind,
    DeterministicFinding,
    RunStatus,
    SpecArtifact,
    get_db_session,
)
from app.main import create_app
from app.services.run_orchestration import RunOrchestrationService
from tests.fixtures.sample_specs import build_valid_spec_json


def _insert_pending_run(
    *,
    session: Session,
    old_spec_bytes: bytes,
    new_spec_bytes: bytes,
) -> UUID:
    run = AnalysisRun(status=RunStatus.PENDING.value)
    session.add(run)
    session.flush()

    for kind, filename, payload in (
        (ArtifactKind.OLD_SPEC, "old.json", old_spec_bytes),
        (ArtifactKind.NEW_SPEC, "new.json", new_spec_bytes),
    ):
        session.add(
            SpecArtifact(
                run_id=run.id,
                kind=kind,
                filename=filename,
                media_type="application/json",
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload),
                payload_bytes=payload,
                payload_text=None,
            )
        )
    session.commit()
    return run.id


def test_get_report_json_integration_returns_persisted_grouped_shape(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_pending_run(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        RunOrchestrationService().process_run(db=session, run_id=run_id)
    finally:
        session.close()

    session = integration_db()
    try:
        app = create_app()

        def override_get_db_session():
            yield session

        app.dependency_overrides[get_db_session] = override_get_db_session
        with TestClient(app) as client:
            response = client.get(f"{Settings().api_prefix}/reports/{run_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["report_id"] == str(run_id)
        assert body["status"] == "completed"
        assert body["summary_counts"]["total_findings"] > 0
        assert body["severity_breakdown"]["high"] >= 0
        assert body["findings_grouped"]
        assert body["llm"]["status"] == "disabled"
        severities = [item["severity"] for item in body["findings_grouped"]]
        assert severities == sorted(
            severities,
            key=lambda item: (
                ("high", "medium", "low").index(item) if item in {"high", "medium", "low"} else 3
            ),
        )

        persisted_findings = (
            session.execute(
                select(DeterministicFinding)
                .where(DeterministicFinding.run_id == run_id)
                .order_by(DeterministicFinding.finding_order)
            )
            .scalars()
            .all()
        )
        assert len(persisted_findings) == body["summary_counts"]["total_findings"]
    finally:
        session.close()
