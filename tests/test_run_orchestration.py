"""Integration tests for run orchestration lifecycle management."""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import get_settings
from app.db import (
    AnalysisRun,
    ArtifactKind,
    DeterministicFinding,
    NormalizedSnapshot,
    RunStatus,
    SpecArtifact,
)
from app.db.session import reset_db_session_state
from app.services.run_orchestration import (
    InProcessRunExecutor,
    RunAlreadyCompletedError,
    RunAlreadyProcessingError,
    RunOrchestrationService,
    RunStageExecutionError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = REPO_ROOT / "alembic"
TEST_DB_ENV_VAR = "TEST_POSTGRES_DATABASE_URL"


def _build_valid_spec_json(*, title: str, include_patch: bool) -> bytes:
    patch_part = (
        """
            "patch": {
                "responses": {"200": {"description": "updated"}}
            },
        """
        if include_patch
        else ""
    )
    return f"""
{{
  "openapi": "3.0.3",
  "info": {{"title": "{title}", "version": "1.0.0"}},
  "paths": {{
    "/pets": {{
      "get": {{
        "responses": {{
          "200": {{
            "description": "ok",
            "content": {{
              "application/json": {{
                "schema": {{
                  "type": "object",
                  "properties": {{
                    "status": {{"type": "string", "enum": ["active", "disabled"]}}
                  }}
                }}
              }}
            }}
          }}
        }}
      }},
      {patch_part}
      "post": {{
        "requestBody": {{
          "required": false,
          "content": {{
            "application/json": {{
              "schema": {{
                "type": "object",
                "properties": {{
                  "name": {{"type": "string"}}
                }}
              }}
            }}
          }}
        }},
        "responses": {{"201": {{"description": "created"}}}}
      }}
    }}
  }}
}}
""".encode()


def _load_test_database_url() -> str:
    test_database_url = os.getenv(TEST_DB_ENV_VAR)
    if not test_database_url:
        pytest.skip(f"{TEST_DB_ENV_VAR} is not set; skipping orchestration integration tests.")
    return test_database_url


def _assert_safe_test_database(url: URL) -> None:
    database_name = (url.database or "").lower()
    if "test" not in database_name:
        msg = (
            "Refusing to run integration test on a non-test database. "
            f"Set {TEST_DB_ENV_VAR} to a database name containing 'test'."
        )
        raise RuntimeError(msg)


def _build_alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _reset_target_schema(database_url: str) -> None:
    tables_to_drop = [
        "audit_logs",
        "migration_tasks",
        "deterministic_findings",
        "normalized_snapshots",
        "spec_artifacts",
        "analysis_runs",
        "alembic_version",
    ]
    engine = sa.create_engine(database_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        for table_name in tables_to_drop:
            connection.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
    engine.dispose()


def _prepare_alembic_runtime(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_db_session_state()
    return _build_alembic_config(database_url)


def _insert_run_with_specs(
    *,
    session: Session,
    old_spec_bytes: bytes,
    new_spec_bytes: bytes,
    status: str = RunStatus.PENDING.value,
) -> uuid.UUID:
    run = AnalysisRun(
        status=status,
        attempt_count=0,
        locked_at=None,
        processing_started_at=None,
        failed_at=None,
        completed_at=None,
        failure_stage=None,
        error_code=None,
        failure_reason=None,
    )
    session.add(run)
    session.flush()

    old_artifact = SpecArtifact(
        run_id=run.id,
        kind=ArtifactKind.OLD_SPEC,
        filename="old.json",
        media_type="application/json",
        sha256=hashlib.sha256(old_spec_bytes).hexdigest(),
        byte_size=len(old_spec_bytes),
        payload_bytes=old_spec_bytes,
        payload_text=None,
    )
    new_artifact = SpecArtifact(
        run_id=run.id,
        kind=ArtifactKind.NEW_SPEC,
        filename="new.json",
        media_type="application/json",
        sha256=hashlib.sha256(new_spec_bytes).hexdigest(),
        byte_size=len(new_spec_bytes),
        payload_bytes=new_spec_bytes,
        payload_text=None,
    )
    session.add(old_artifact)
    session.add(new_artifact)
    session.commit()
    return run.id


@pytest.fixture()
def integration_db(monkeypatch: pytest.MonkeyPatch):
    test_database_url = _load_test_database_url()
    parsed_url = make_url(test_database_url)
    _assert_safe_test_database(parsed_url)
    _reset_target_schema(test_database_url)
    alembic_config = _prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(test_database_url)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield session_factory
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        reset_db_session_state()
        get_settings.cache_clear()


def test_orchestration_success_path_persists_findings_and_completes_run(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=_build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=_build_valid_spec_json(title="New API", include_patch=True),
        )
    finally:
        session.close()

    session = integration_db()
    try:
        service = RunOrchestrationService()
        run = service.process_run(db=session, run_id=run_id)

        assert run.status == RunStatus.COMPLETED.value
        assert run.attempt_count == 1
        assert run.processing_started_at is not None
        assert run.completed_at is not None
        assert run.locked_at is None

        snapshot_count = session.scalar(
            select(func.count())
            .select_from(NormalizedSnapshot)
            .where(NormalizedSnapshot.run_id == run_id)
        )
        finding_rows = (
            session.execute(
                select(DeterministicFinding)
                .where(DeterministicFinding.run_id == run_id)
                .order_by(DeterministicFinding.finding_order)
            )
            .scalars()
            .all()
        )

        assert snapshot_count == 2
        assert len(finding_rows) > 0
        assert [row.finding_order for row in finding_rows] == list(range(1, len(finding_rows) + 1))
        assert all(row.severity in {"low", "medium", "high"} for row in finding_rows)
        assert all(row.detail for row in finding_rows)
    finally:
        session.close()


def test_orchestration_invalid_spec_records_failure_stage_and_error_code(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=b'{"openapi":',
            new_spec_bytes=_build_valid_spec_json(title="New API", include_patch=False),
        )
    finally:
        session.close()

    session = integration_db()
    try:
        service = RunOrchestrationService()
        with pytest.raises(RunStageExecutionError) as exc_info:
            service.process_run(db=session, run_id=run_id)
        assert exc_info.value.stage.value == "parse_spec_old"
        assert exc_info.value.error_code == "openapi_parse_error"
    finally:
        session.close()

    session = integration_db()
    try:
        failed_run = session.get(AnalysisRun, run_id)
        assert failed_run is not None
        assert failed_run.status == RunStatus.FAILED.value
        assert failed_run.failed_at is not None
        assert failed_run.locked_at is None
        assert failed_run.failure_stage == "parse_spec_old"
        assert failed_run.error_code == "openapi_parse_error"
        assert failed_run.attempt_count == 1
    finally:
        session.close()


def test_orchestration_duplicate_processing_protection(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=_build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=_build_valid_spec_json(title="New API", include_patch=False),
            status=RunStatus.PROCESSING.value,
        )
        run = session.get(AnalysisRun, run_id)
        assert run is not None
        run.locked_at = datetime.now(tz=UTC)
        run.processing_started_at = datetime.now(tz=UTC)
        run.attempt_count = 1
        session.commit()
    finally:
        session.close()

    session = integration_db()
    try:
        service = RunOrchestrationService()
        with pytest.raises(RunAlreadyProcessingError):
            service.process_run(db=session, run_id=run_id)
    finally:
        session.close()


def test_orchestration_reprocessing_completed_run_returns_domain_error(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=_build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=_build_valid_spec_json(title="New API", include_patch=True),
        )
    finally:
        session.close()

    session = integration_db()
    try:
        service = RunOrchestrationService()
        completed = service.process_run(db=session, run_id=run_id)
        assert completed.status == RunStatus.COMPLETED.value
    finally:
        session.close()

    session = integration_db()
    try:
        service = RunOrchestrationService()
        with pytest.raises(RunAlreadyCompletedError):
            service.process_run(db=session, run_id=run_id)
    finally:
        session.close()


def test_orchestration_concurrent_claim_allows_only_one_processor(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=_build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=_build_valid_spec_json(title="New API", include_patch=True),
        )
    finally:
        session.close()

    entered = threading.Event()
    release = threading.Event()
    outcome: Queue[object] = Queue()

    class BlockingExecutor(InProcessRunExecutor):
        def execute(self, *, db: Session, run: AnalysisRun):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Timed out waiting to release blocking executor.")
            return super().execute(db=db, run=run)

    def _worker() -> None:
        worker_session = integration_db()
        try:
            service = RunOrchestrationService(executor=BlockingExecutor())
            run = service.process_run(db=worker_session, run_id=run_id)
            outcome.put(run.status)
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            outcome.put(exc)
        finally:
            worker_session.close()

    worker_thread = threading.Thread(target=_worker)
    worker_thread.start()
    assert entered.wait(timeout=5), "Primary processor did not start in time."

    session = integration_db()
    try:
        second_service = RunOrchestrationService()
        with pytest.raises(RunAlreadyProcessingError):
            second_service.process_run(db=session, run_id=run_id)
    finally:
        session.close()

    release.set()
    worker_thread.join(timeout=10)
    assert not worker_thread.is_alive()

    result = outcome.get(timeout=2)
    if isinstance(result, Exception):
        raise result
    assert result == RunStatus.COMPLETED.value
