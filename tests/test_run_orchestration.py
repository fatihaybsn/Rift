"""Integration tests for run orchestration lifecycle management."""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import UTC, datetime
from queue import Queue

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import (
    AnalysisRun,
    ArtifactKind,
    AuditLog,
    DeterministicFinding,
    NormalizedSnapshot,
    RunStatus,
    SpecArtifact,
)
from app.services.changelog_interpreter import (
    ChangelogInterpretationResult,
    ChangelogTaskSuggestion,
    NoLLMChangelogProvider,
)
from app.services.run_orchestration import (
    InProcessRunExecutor,
    PipelineStage,
    RunAlreadyCompletedError,
    RunAlreadyProcessingError,
    RunOrchestrationService,
    RunStageExecutionError,
)
from tests.fixtures.sample_specs import build_valid_spec_json


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


def _insert_changelog_artifact(*, session: Session, run_id: uuid.UUID, changelog_text: str) -> None:
    encoded = changelog_text.encode("utf-8")
    session.add(
        SpecArtifact(
            run_id=run_id,
            kind=ArtifactKind.CHANGELOG_TEXT,
            filename=None,
            media_type="text/plain",
            sha256=hashlib.sha256(encoded).hexdigest(),
            byte_size=len(encoded),
            payload_bytes=None,
            payload_text=changelog_text,
        )
    )
    session.commit()


class _MockChangelogProvider:
    def __init__(
        self,
        *,
        result: ChangelogInterpretationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error

    def interpret(self, *, prompt: str, changelog_text: str) -> ChangelogInterpretationResult:
        assert "Interpret changelog text only" in prompt
        assert changelog_text
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def test_orchestration_success_path_persists_findings_and_completes_run(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
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
        audit_rows = (
            session.execute(select(AuditLog).where(AuditLog.run_id == run_id)).scalars().all()
        )

        assert snapshot_count == 2
        assert len(finding_rows) > 0
        assert [row.finding_order for row in finding_rows] == list(range(1, len(finding_rows) + 1))
        assert all(row.severity in {"low", "medium", "high"} for row in finding_rows)
        assert all(row.detail for row in finding_rows)

        stage_events = sorted(
            [row.payload_json for row in audit_rows if row.event_type == "run_stage_transition"],
            key=lambda payload: payload["event_index"],
        )
        status_events = sorted(
            [row.payload_json for row in audit_rows if row.event_type == "run_status_transition"],
            key=lambda payload: payload["event_index"],
        )
        expected_stage_order = [
            PipelineStage.LOAD_ARTIFACTS.value,
            PipelineStage.PARSE_SPEC_OLD.value,
            PipelineStage.PARSE_SPEC_NEW.value,
            PipelineStage.VALIDATE_SPEC_OLD.value,
            PipelineStage.VALIDATE_SPEC_NEW.value,
            PipelineStage.NORMALIZE_OLD.value,
            PipelineStage.NORMALIZE_NEW.value,
            PipelineStage.COMPUTE_DIFF.value,
            PipelineStage.APPLY_SEVERITY.value,
            PipelineStage.PERSIST_RESULTS.value,
        ]
        expected_stage_transitions = [
            item
            for stage in expected_stage_order
            for item in ((stage, "started"), (stage, "succeeded"))
        ]

        assert len(status_events) == 2
        assert status_events[0]["from_status"] == RunStatus.PENDING.value
        assert status_events[0]["to_status"] == RunStatus.PROCESSING.value
        assert status_events[1]["from_status"] == RunStatus.PROCESSING.value
        assert status_events[1]["to_status"] == RunStatus.COMPLETED.value
        observed_stage_transitions = [(item["stage"], item["transition"]) for item in stage_events]
        assert observed_stage_transitions == expected_stage_transitions
        assert all(item["attempt_count"] == 1 for item in stage_events)
    finally:
        session.close()


def test_orchestration_invalid_spec_records_failure_stage_and_error_code(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=b'{"openapi":',
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=False),
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
        audit_rows = (
            session.execute(select(AuditLog).where(AuditLog.run_id == run_id)).scalars().all()
        )
        assert failed_run is not None
        assert failed_run.status == RunStatus.FAILED.value
        assert failed_run.failed_at is not None
        assert failed_run.locked_at is None
        assert failed_run.failure_stage == "parse_spec_old"
        assert failed_run.error_code == "openapi_parse_error"
        assert failed_run.attempt_count == 1

        stage_events = sorted(
            [row.payload_json for row in audit_rows if row.event_type == "run_stage_transition"],
            key=lambda payload: payload["event_index"],
        )
        status_events = sorted(
            [row.payload_json for row in audit_rows if row.event_type == "run_status_transition"],
            key=lambda payload: payload["event_index"],
        )

        assert len(status_events) == 2
        assert status_events[0]["from_status"] == RunStatus.PENDING.value
        assert status_events[0]["to_status"] == RunStatus.PROCESSING.value
        assert status_events[1]["from_status"] == RunStatus.PROCESSING.value
        assert status_events[1]["to_status"] == RunStatus.FAILED.value
        assert status_events[1]["failure_stage"] == PipelineStage.PARSE_SPEC_OLD.value
        assert status_events[1]["error_code"] == "openapi_parse_error"
        assert [(item["stage"], item["transition"]) for item in stage_events] == [
            (PipelineStage.LOAD_ARTIFACTS.value, "started"),
            (PipelineStage.LOAD_ARTIFACTS.value, "succeeded"),
            (PipelineStage.PARSE_SPEC_OLD.value, "started"),
            (PipelineStage.PARSE_SPEC_OLD.value, "failed"),
        ]
        assert stage_events[-1]["error_code"] == "openapi_parse_error"
    finally:
        session.close()


def test_orchestration_duplicate_processing_protection(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=False),
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
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
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
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
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


def test_llm_feature_flag_off_sets_disabled_without_mutating_run_status(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id,
            changelog_text="Removed deprecated endpoint and renamed response field.",
        )
    finally:
        session.close()

    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=False,
        )
        run = RunOrchestrationService(settings=settings).process_run(db=session, run_id=run_id)

        assert run.status == RunStatus.COMPLETED.value
        assert run.llm_status == "disabled"
        assert run.llm_summary is None
        assert run.llm_migration_tasks is None
        assert run.llm_confidence is None
        assert run.llm_explanation is None
        assert run.llm_error_code is None
    finally:
        session.close()


def test_llm_feature_flag_on_with_mock_response_persists_separate_ai_fields(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id,
            changelog_text="Patch endpoint added; old endpoint removed.",
        )
    finally:
        session.close()

    provider = _MockChangelogProvider(
        result=ChangelogInterpretationResult(
            summary="Changelog indicates endpoint replacement and request updates.",
            migration_tasks=(
                ChangelogTaskSuggestion(
                    title="Update endpoint calls",
                    detail="Switch consumers to the new patch endpoint.",
                    priority=1,
                ),
                ChangelogTaskSuggestion(
                    title="Validate request payload mapping",
                    detail="Confirm required request fields for replacement endpoint.",
                    priority=2,
                ),
            ),
            confidence=0.91,
            explanation="High overlap with deterministic findings in changelog text.",
            requires_manual_review=False,
            provider="mock",
            model="mock-1",
        )
    )

    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
            llm_low_confidence_threshold=0.6,
        )
        run = RunOrchestrationService(settings=settings, changelog_provider=provider).process_run(
            db=session,
            run_id=run_id,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.llm_status == "completed"
        assert run.llm_summary is not None
        assert run.llm_confidence == 0.91
        assert run.llm_explanation == "High overlap with deterministic findings in changelog text."
        assert run.llm_provider == "mock"
        assert run.llm_model == "mock-1"
        assert run.llm_completed_at is not None
        assert isinstance(run.llm_migration_tasks, list)
        assert len(run.llm_migration_tasks) == 2
    finally:
        session.close()


def test_llm_feature_flag_on_uses_default_no_provider_fallback(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id,
            changelog_text="Small changelog note without deterministic authority.",
        )
    finally:
        session.close()

    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
            llm_low_confidence_threshold=0.6,
        )
        service = RunOrchestrationService(settings=settings)
        run = service.process_run(db=session, run_id=run_id)

        assert run.status == RunStatus.COMPLETED.value
        assert run.llm_status == "manual_review_required"
        assert run.llm_summary == "No LLM provider configured."
        assert run.llm_confidence == 0.0
        assert run.llm_explanation == "AI enrichment fallback mode is active."
        assert run.llm_provider == "none"
        assert run.llm_model == "none"
        assert run.llm_error_code is None
        assert run.llm_completed_at is not None
        assert run.llm_migration_tasks == []

        assert isinstance(service._changelog_provider, NoLLMChangelogProvider)
    finally:
        session.close()


def test_llm_low_confidence_maps_to_manual_review_required_only(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id,
            changelog_text="Potentially risky contract updates.",
        )
    finally:
        session.close()

    provider = _MockChangelogProvider(
        result=ChangelogInterpretationResult(
            summary="Potential contract risk noted in changelog.",
            migration_tasks=(),
            confidence=0.34,
            explanation="Unclear migration language.",
            requires_manual_review=False,
            provider="mock",
            model="mock-low",
        )
    )

    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
            llm_low_confidence_threshold=0.6,
        )
        run = RunOrchestrationService(settings=settings, changelog_provider=provider).process_run(
            db=session,
            run_id=run_id,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.llm_status == "manual_review_required"
        assert run.llm_explanation == "Unclear migration language."
        assert run.llm_error_code is None
    finally:
        session.close()


def test_llm_provider_failure_falls_back_without_mutating_run_status(integration_db) -> None:
    session = integration_db()
    try:
        run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id,
            changelog_text="Breaking changes described with sparse detail.",
        )
    finally:
        session.close()

    provider = _MockChangelogProvider(error=RuntimeError("provider unavailable"))
    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
        )
        run = RunOrchestrationService(settings=settings, changelog_provider=provider).process_run(
            db=session,
            run_id=run_id,
        )

        assert run.status == RunStatus.COMPLETED.value
        assert run.llm_status == "failed"
        assert run.llm_error_code == "llm_provider_error"
        assert run.llm_summary is None
        assert run.llm_confidence is None
        assert run.llm_explanation is None
    finally:
        session.close()


def test_enabling_llm_does_not_change_deterministic_findings(integration_db) -> None:
    session = integration_db()
    try:
        run_id_without_llm = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        run_id_with_llm = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=run_id_with_llm,
            changelog_text="Endpoint replacement and schema updates.",
        )
    finally:
        session.close()

    session = integration_db()
    try:
        baseline_settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=False,
        )
        baseline_run = RunOrchestrationService(settings=baseline_settings).process_run(
            db=session,
            run_id=run_id_without_llm,
        )
        baseline_findings = (
            session.execute(
                select(DeterministicFinding)
                .where(DeterministicFinding.run_id == baseline_run.id)
                .order_by(DeterministicFinding.finding_order, DeterministicFinding.finding_key)
            )
            .scalars()
            .all()
        )
    finally:
        session.close()

    provider = _MockChangelogProvider(
        result=ChangelogInterpretationResult(
            summary="High-level migration notes.",
            migration_tasks=(),
            confidence=0.88,
            explanation="Strong textual match.",
            requires_manual_review=False,
            provider="mock",
            model="mock-determinism",
        )
    )
    session = integration_db()
    try:
        llm_settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
        )
        llm_run = RunOrchestrationService(
            settings=llm_settings,
            changelog_provider=provider,
        ).process_run(db=session, run_id=run_id_with_llm)
        llm_findings = (
            session.execute(
                select(DeterministicFinding)
                .where(DeterministicFinding.run_id == llm_run.id)
                .order_by(DeterministicFinding.finding_order, DeterministicFinding.finding_key)
            )
            .scalars()
            .all()
        )

        baseline_projection = [
            (
                item.finding_order,
                item.finding_key,
                item.category,
                item.location,
                item.http_method,
                item.severity,
                item.title,
                item.detail,
                item.metadata_json,
            )
            for item in baseline_findings
        ]
        llm_projection = [
            (
                item.finding_order,
                item.finding_key,
                item.category,
                item.location,
                item.http_method,
                item.severity,
                item.title,
                item.detail,
                item.metadata_json,
            )
            for item in llm_findings
        ]
        assert baseline_projection == llm_projection
    finally:
        session.close()


def test_llm_outcomes_never_mutate_main_run_status(integration_db) -> None:
    session = integration_db()
    try:
        manual_review_run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        failed_run_id = _insert_run_with_specs(
            session=session,
            old_spec_bytes=build_valid_spec_json(title="Old API", include_patch=False),
            new_spec_bytes=build_valid_spec_json(title="New API", include_patch=True),
        )
        _insert_changelog_artifact(
            session=session,
            run_id=manual_review_run_id,
            changelog_text="Potentially breaking updates.",
        )
        _insert_changelog_artifact(
            session=session,
            run_id=failed_run_id,
            changelog_text="Potentially breaking updates.",
        )
    finally:
        session.close()

    manual_review_provider = _MockChangelogProvider(
        result=ChangelogInterpretationResult(
            summary="Needs extra review.",
            migration_tasks=(),
            confidence=0.2,
            explanation="Low confidence output.",
            requires_manual_review=False,
            provider="mock",
            model="mock-manual-review",
        )
    )
    failed_provider = _MockChangelogProvider(error=RuntimeError("llm timeout"))

    session = integration_db()
    try:
        settings = Settings(
            _env_file=None,
            llm_changelog_interpreter_enabled=True,
            llm_low_confidence_threshold=0.6,
        )
        manual_review_run = RunOrchestrationService(
            settings=settings,
            changelog_provider=manual_review_provider,
        ).process_run(db=session, run_id=manual_review_run_id)
        failed_run = RunOrchestrationService(
            settings=settings,
            changelog_provider=failed_provider,
        ).process_run(db=session, run_id=failed_run_id)

        assert manual_review_run.status == RunStatus.COMPLETED.value
        assert manual_review_run.llm_status == "manual_review_required"
        assert failed_run.status == RunStatus.COMPLETED.value
        assert failed_run.llm_status == "failed"
    finally:
        session.close()
