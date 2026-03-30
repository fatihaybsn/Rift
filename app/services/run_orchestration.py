"""Run orchestration service for deterministic analysis lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol

from opentelemetry.trace import Status, StatusCode
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.diff_engine import CompatibilityClassification, diff_canonical_snapshots
from app.core.openapi_processing import (
    CanonicalOpenAPISnapshot,
    OpenAPIProcessingError,
    normalize_openapi_document,
    parse_openapi_document,
    validate_openapi_document,
)
from app.core.severity_engine import ClassifiedFinding, classify_findings
from app.db import (
    AnalysisRun,
    ArtifactKind,
    AuditLog,
    DeterministicFinding,
    NormalizedSnapshot,
    RunStatus,
    SnapshotKind,
    SpecArtifact,
)
from app.logging import get_logger
from app.observability import get_tracer, record_run_failure, record_run_success

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class PipelineStage(StrEnum):
    """Explicit orchestration stages for deterministic run processing."""

    LOAD_ARTIFACTS = "load_artifacts"
    PARSE_SPEC_OLD = "parse_spec_old"
    PARSE_SPEC_NEW = "parse_spec_new"
    VALIDATE_SPEC_OLD = "validate_spec_old"
    VALIDATE_SPEC_NEW = "validate_spec_new"
    NORMALIZE_OLD = "normalize_old"
    NORMALIZE_NEW = "normalize_new"
    COMPUTE_DIFF = "compute_diff"
    APPLY_SEVERITY = "apply_severity"
    PERSIST_RESULTS = "persist_results"


class RunOrchestrationError(RuntimeError):
    """Base error type for orchestration failures."""


class RunNotFoundError(RunOrchestrationError):
    """Raised when the target run id does not exist."""


class RunAlreadyProcessingError(RunOrchestrationError):
    """Raised when a run is already being processed."""


class RunAlreadyCompletedError(RunOrchestrationError):
    """Raised when a completed run is re-processed."""


class RunInvalidStateError(RunOrchestrationError):
    """Raised when run state does not allow processing."""


class RunStageExecutionError(RunOrchestrationError):
    """Raised when execution fails at a specific pipeline stage."""

    def __init__(self, *, stage: PipelineStage, error_code: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.error_code = error_code


class StageTransitionType(StrEnum):
    """Typed stage transition names for audit events."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionPayload:
    """Executor output passed to persistence stage."""

    old_artifact: SpecArtifact
    new_artifact: SpecArtifact
    old_snapshot: CanonicalOpenAPISnapshot
    new_snapshot: CanonicalOpenAPISnapshot
    classified_findings: tuple[ClassifiedFinding, ...]


class RunExecutor(Protocol):
    """Narrow seam for alternative execution mechanisms."""

    def execute(self, *, db: Session, run: AnalysisRun) -> ExecutionPayload:
        """Execute deterministic stages up to persisted payload generation."""


StageEventCallback = Callable[
    [PipelineStage, StageTransitionType, str | None, str | None],
    None,
]


@dataclass(frozen=True)
class StageTransitionEvent:
    """Captured stage transition used for persisted audit logs."""

    stage: PipelineStage
    transition: StageTransitionType
    error_code: str | None
    message: str | None


class InProcessRunExecutor:
    """Default synchronous, in-process execution strategy for MVP reliability."""

    def __init__(self) -> None:
        self._stage_event_callback: StageEventCallback | None = None

    def set_stage_event_callback(self, callback: StageEventCallback | None) -> None:
        """Register callback used for persisted stage-transition events."""
        self._stage_event_callback = callback

    def execute(self, *, db: Session, run: AnalysisRun) -> ExecutionPayload:
        old_artifact, new_artifact = self._run_stage(
            stage=PipelineStage.LOAD_ARTIFACTS,
            error_code="artifacts_missing",
            func=self._load_spec_artifacts,
            db=db,
            run_id=run.id,
        )

        old_document = self._run_stage(
            stage=PipelineStage.PARSE_SPEC_OLD,
            error_code="openapi_parse_error",
            func=parse_openapi_document,
            raw_bytes=old_artifact.payload_bytes,
            source=ArtifactKind.OLD_SPEC.value,
        )
        new_document = self._run_stage(
            stage=PipelineStage.PARSE_SPEC_NEW,
            error_code="openapi_parse_error",
            func=parse_openapi_document,
            raw_bytes=new_artifact.payload_bytes,
            source=ArtifactKind.NEW_SPEC.value,
        )

        old_version = self._run_stage(
            stage=PipelineStage.VALIDATE_SPEC_OLD,
            error_code="openapi_validation_error",
            func=validate_openapi_document,
            document=old_document,
            source=ArtifactKind.OLD_SPEC.value,
        )
        new_version = self._run_stage(
            stage=PipelineStage.VALIDATE_SPEC_NEW,
            error_code="openapi_validation_error",
            func=validate_openapi_document,
            document=new_document,
            source=ArtifactKind.NEW_SPEC.value,
        )

        old_snapshot = self._run_stage(
            stage=PipelineStage.NORMALIZE_OLD,
            error_code="openapi_normalization_error",
            func=normalize_openapi_document,
            document=old_document,
            openapi_version=old_version,
            schema_version="v1",
        )
        new_snapshot = self._run_stage(
            stage=PipelineStage.NORMALIZE_NEW,
            error_code="openapi_normalization_error",
            func=normalize_openapi_document,
            document=new_document,
            openapi_version=new_version,
            schema_version="v1",
        )

        findings = self._run_stage(
            stage=PipelineStage.COMPUTE_DIFF,
            error_code="diff_compute_error",
            func=diff_canonical_snapshots,
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot,
        )
        classified_findings = self._run_stage(
            stage=PipelineStage.APPLY_SEVERITY,
            error_code="severity_apply_error",
            func=classify_findings,
            findings=findings,
        )

        return ExecutionPayload(
            old_artifact=old_artifact,
            new_artifact=new_artifact,
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot,
            classified_findings=classified_findings,
        )

    def _load_spec_artifacts(
        self,
        *,
        db: Session,
        run_id: uuid.UUID,
    ) -> tuple[SpecArtifact, SpecArtifact]:
        rows = (
            db.execute(
                select(SpecArtifact).where(
                    SpecArtifact.run_id == run_id,
                    SpecArtifact.kind.in_((ArtifactKind.OLD_SPEC, ArtifactKind.NEW_SPEC)),
                )
            )
            .scalars()
            .all()
        )
        artifacts = {artifact.kind: artifact for artifact in rows}
        missing_kinds = [
            kind.value
            for kind in (ArtifactKind.OLD_SPEC, ArtifactKind.NEW_SPEC)
            if kind not in artifacts
        ]
        if missing_kinds:
            raise RunStageExecutionError(
                stage=PipelineStage.LOAD_ARTIFACTS,
                error_code="artifacts_missing",
                message=f"Run is missing required artifacts: {', '.join(missing_kinds)}.",
            )

        old_artifact = artifacts[ArtifactKind.OLD_SPEC]
        new_artifact = artifacts[ArtifactKind.NEW_SPEC]
        if old_artifact.payload_bytes is None or new_artifact.payload_bytes is None:
            raise RunStageExecutionError(
                stage=PipelineStage.LOAD_ARTIFACTS,
                error_code="artifact_payload_missing",
                message="Spec artifacts must contain bytes payloads.",
            )

        return old_artifact, new_artifact

    def _run_stage(
        self,
        *,
        stage: PipelineStage,
        error_code: str,
        func: object,
        **kwargs: object,
    ) -> object:
        with tracer.start_as_current_span(f"run.stage.{stage.value}") as span:
            span.set_attribute("run.pipeline.stage", stage.value)
            try:
                self._emit_stage_transition(stage=stage, transition=StageTransitionType.STARTED)
                result = func(**kwargs)  # type: ignore[misc]
                self._emit_stage_transition(stage=stage, transition=StageTransitionType.SUCCEEDED)
                span.set_status(Status(StatusCode.OK))
                return result
            except RunStageExecutionError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._emit_stage_transition(
                    stage=stage,
                    transition=StageTransitionType.FAILED,
                    error_code=exc.error_code,
                    message=str(exc),
                )
                raise
            except OpenAPIProcessingError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._emit_stage_transition(
                    stage=stage,
                    transition=StageTransitionType.FAILED,
                    error_code=error_code,
                    message=str(exc),
                )
                raise RunStageExecutionError(
                    stage=stage,
                    error_code=error_code,
                    message=str(exc),
                ) from exc
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._emit_stage_transition(
                    stage=stage,
                    transition=StageTransitionType.FAILED,
                    error_code=error_code,
                    message=str(exc),
                )
                raise RunStageExecutionError(
                    stage=stage,
                    error_code=error_code,
                    message=str(exc),
                ) from exc

    def _emit_stage_transition(
        self,
        *,
        stage: PipelineStage,
        transition: StageTransitionType,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        if self._stage_event_callback is None:
            return
        self._stage_event_callback(stage, transition, error_code, message)


class RunOrchestrationService:
    """Application service orchestrating run lifecycle transitions."""

    def __init__(self, *, executor: RunExecutor | None = None) -> None:
        self._executor = executor or InProcessRunExecutor()

    def process_run(self, *, db: Session, run_id: uuid.UUID) -> AnalysisRun:
        """Process one run synchronously from pending to completed/failed."""
        started_at = perf_counter()
        self._claim_pending_run(db=db, run_id=run_id)
        run = db.get(AnalysisRun, run_id)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} was not found after claim.")
        run_logger = logger.bind(run_id=str(run.id), attempt_count=run.attempt_count)

        with tracer.start_as_current_span("run.process") as run_span:
            run_span.set_attribute("run.id", str(run.id))
            run_span.set_attribute("run.attempt_count", run.attempt_count)
            run_span.set_attribute("run.status.initial", run.status)
            run_logger.info("run_processing_started", status=run.status)

            stage_events: list[StageTransitionEvent] = []
            self._set_stage_event_callback(
                callback=lambda stage, transition, error_code, message: stage_events.append(
                    StageTransitionEvent(
                        stage=stage,
                        transition=transition,
                        error_code=error_code,
                        message=message,
                    )
                )
            )
            try:
                payload = self._executor.execute(db=db, run=run)
                self._persist_results_with_stage_events(
                    db=db,
                    run=run,
                    payload=payload,
                    stage_events=stage_events,
                )
                run.status = RunStatus.COMPLETED.value
                run.completed_at = datetime.now(tz=UTC)
                run.locked_at = None
                run.failed_at = None
                run.failure_stage = None
                run.error_code = None
                run.failure_reason = None
                self._append_attempt_audit_logs(
                    db=db,
                    run=run,
                    stage_events=stage_events,
                    final_status=RunStatus.COMPLETED,
                    failure_stage=None,
                    failure_error_code=None,
                )
                db.commit()
                db.refresh(run)

                breaking_change_count = _count_breaking_findings(payload.classified_findings)
                duration_seconds = perf_counter() - started_at
                record_run_success(
                    duration_seconds=duration_seconds,
                    breaking_change_count=breaking_change_count,
                )
                run_span.set_attribute("run.status.final", run.status)
                run_span.set_attribute("run.findings_count", len(payload.classified_findings))
                run_span.set_attribute("run.breaking_change_count", breaking_change_count)
                run_span.set_status(Status(StatusCode.OK))
                run_logger.info(
                    "run_processing_completed",
                    final_status=run.status,
                    findings_count=len(payload.classified_findings),
                    breaking_change_count=breaking_change_count,
                    duration_seconds=duration_seconds,
                )
                return run
            except RunStageExecutionError as exc:
                db.rollback()
                self._mark_failed(
                    db=db,
                    run_id=run_id,
                    stage=exc.stage,
                    error_code=exc.error_code,
                    reason=str(exc),
                    stage_events=stage_events,
                )
                duration_seconds = perf_counter() - started_at
                record_run_failure(
                    duration_seconds=duration_seconds,
                    failure_stage=exc.stage.value,
                    error_code=exc.error_code,
                )
                run_span.record_exception(exc)
                run_span.set_status(Status(StatusCode.ERROR, str(exc)))
                run_span.set_attribute("run.status.final", RunStatus.FAILED.value)
                run_span.set_attribute("run.failure_stage", exc.stage.value)
                run_span.set_attribute("run.error_code", exc.error_code)
                run_logger.exception(
                    "run_processing_failed",
                    failure_stage=exc.stage.value,
                    error_code=exc.error_code,
                    duration_seconds=duration_seconds,
                    stage_event_count=len(stage_events),
                )
                raise
            except Exception as exc:
                db.rollback()
                fallback_error = RunStageExecutionError(
                    stage=PipelineStage.PERSIST_RESULTS,
                    error_code="orchestration_unhandled_error",
                    message=str(exc),
                )
                self._mark_failed(
                    db=db,
                    run_id=run_id,
                    stage=fallback_error.stage,
                    error_code=fallback_error.error_code,
                    reason=str(fallback_error),
                    stage_events=stage_events,
                )
                duration_seconds = perf_counter() - started_at
                record_run_failure(
                    duration_seconds=duration_seconds,
                    failure_stage=fallback_error.stage.value,
                    error_code=fallback_error.error_code,
                )
                run_span.record_exception(exc)
                run_span.set_status(Status(StatusCode.ERROR, str(fallback_error)))
                run_span.set_attribute("run.status.final", RunStatus.FAILED.value)
                run_span.set_attribute("run.failure_stage", fallback_error.stage.value)
                run_span.set_attribute("run.error_code", fallback_error.error_code)
                run_logger.exception(
                    "run_processing_failed_unhandled",
                    failure_stage=fallback_error.stage.value,
                    error_code=fallback_error.error_code,
                    duration_seconds=duration_seconds,
                    stage_event_count=len(stage_events),
                )
                raise fallback_error from exc
            finally:
                self._set_stage_event_callback(None)

    def _claim_pending_run(self, *, db: Session, run_id: uuid.UUID) -> None:
        claim_stmt = (
            update(AnalysisRun)
            .where(
                AnalysisRun.id == run_id,
                AnalysisRun.status == RunStatus.PENDING.value,
            )
            .values(
                status=RunStatus.PROCESSING.value,
                attempt_count=AnalysisRun.attempt_count + 1,
                locked_at=func.now(),
                processing_started_at=func.now(),
                completed_at=None,
                failed_at=None,
                failure_stage=None,
                error_code=None,
                failure_reason=None,
            )
        )
        claim_result = db.execute(claim_stmt)
        if claim_result.rowcount == 1:
            db.commit()
            return

        db.rollback()
        existing = db.get(AnalysisRun, run_id)
        if existing is None:
            raise RunNotFoundError(f"Run {run_id} does not exist.")
        if existing.status == RunStatus.PROCESSING.value:
            raise RunAlreadyProcessingError(f"Run {run_id} is already processing.")
        if existing.status == RunStatus.COMPLETED.value:
            raise RunAlreadyCompletedError(f"Run {run_id} is already completed.")
        raise RunInvalidStateError(
            f"Run {run_id} cannot be claimed from status {existing.status!r}."
        )

    def _persist_results(self, *, db: Session, run: AnalysisRun, payload: ExecutionPayload) -> None:
        try:
            db.execute(delete(DeterministicFinding).where(DeterministicFinding.run_id == run.id))
            db.execute(delete(NormalizedSnapshot).where(NormalizedSnapshot.run_id == run.id))

            db.add(
                NormalizedSnapshot(
                    run_id=run.id,
                    source_artifact=payload.old_artifact,
                    kind=SnapshotKind.OLD,
                    schema_version=payload.old_snapshot.schema_version,
                    content_json=payload.old_snapshot.to_dict(),
                    checksum=payload.old_snapshot.checksum(),
                )
            )
            db.add(
                NormalizedSnapshot(
                    run_id=run.id,
                    source_artifact=payload.new_artifact,
                    kind=SnapshotKind.NEW,
                    schema_version=payload.new_snapshot.schema_version,
                    content_json=payload.new_snapshot.to_dict(),
                    checksum=payload.new_snapshot.checksum(),
                )
            )

            for order, classified in enumerate(payload.classified_findings, start=1):
                finding = classified.finding
                db.add(
                    DeterministicFinding(
                        run_id=run.id,
                        finding_key=_build_finding_key(order=order, sort_key=finding.sort_key),
                        finding_order=order,
                        category=finding.category.value,
                        location=finding.locator,
                        http_method=finding.method,
                        severity=classified.severity.value,
                        title=finding.code.value.replace("_", " ").capitalize(),
                        detail=classified.explanation,
                        metadata_json=finding.to_dict(),
                    )
                )
        except Exception as exc:
            raise RunStageExecutionError(
                stage=PipelineStage.PERSIST_RESULTS,
                error_code="persist_results_error",
                message=str(exc),
            ) from exc

    def _persist_results_with_stage_events(
        self,
        *,
        db: Session,
        run: AnalysisRun,
        payload: ExecutionPayload,
        stage_events: list[StageTransitionEvent],
    ) -> None:
        persist_span_name = f"run.stage.{PipelineStage.PERSIST_RESULTS.value}"
        with tracer.start_as_current_span(persist_span_name) as span:
            span.set_attribute("run.pipeline.stage", PipelineStage.PERSIST_RESULTS.value)
            stage_events.append(
                StageTransitionEvent(
                    stage=PipelineStage.PERSIST_RESULTS,
                    transition=StageTransitionType.STARTED,
                    error_code=None,
                    message=None,
                )
            )
            try:
                self._persist_results(db=db, run=run, payload=payload)
            except RunStageExecutionError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                stage_events.append(
                    StageTransitionEvent(
                        stage=PipelineStage.PERSIST_RESULTS,
                        transition=StageTransitionType.FAILED,
                        error_code=exc.error_code,
                        message=str(exc),
                    )
                )
                raise
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                stage_events.append(
                    StageTransitionEvent(
                        stage=PipelineStage.PERSIST_RESULTS,
                        transition=StageTransitionType.FAILED,
                        error_code="persist_results_error",
                        message=str(exc),
                    )
                )
                raise RunStageExecutionError(
                    stage=PipelineStage.PERSIST_RESULTS,
                    error_code="persist_results_error",
                    message=str(exc),
                ) from exc

            span.set_status(Status(StatusCode.OK))
            stage_events.append(
                StageTransitionEvent(
                    stage=PipelineStage.PERSIST_RESULTS,
                    transition=StageTransitionType.SUCCEEDED,
                    error_code=None,
                    message=None,
                )
            )

    def _mark_failed(
        self,
        *,
        db: Session,
        run_id: uuid.UUID,
        stage: PipelineStage,
        error_code: str,
        reason: str,
        stage_events: list[StageTransitionEvent],
    ) -> None:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} does not exist.")
        db.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(
                status=RunStatus.FAILED.value,
                locked_at=None,
                completed_at=None,
                failed_at=func.now(),
                failure_stage=stage.value,
                error_code=error_code,
                failure_reason=reason,
            )
        )
        run.status = RunStatus.FAILED.value
        run.failure_stage = stage.value
        run.error_code = error_code
        self._append_attempt_audit_logs(
            db=db,
            run=run,
            stage_events=stage_events,
            final_status=RunStatus.FAILED,
            failure_stage=stage,
            failure_error_code=error_code,
        )
        db.commit()

    def _append_attempt_audit_logs(
        self,
        *,
        db: Session,
        run: AnalysisRun,
        stage_events: list[StageTransitionEvent],
        final_status: RunStatus,
        failure_stage: PipelineStage | None,
        failure_error_code: str | None,
    ) -> None:
        event_index = 0

        event_index += 1
        db.add(
            AuditLog(
                run_id=run.id,
                event_type="run_status_transition",
                actor="system:orchestrator",
                payload_json={
                    "event_index": event_index,
                    "attempt_count": run.attempt_count,
                    "from_status": RunStatus.PENDING.value,
                    "to_status": RunStatus.PROCESSING.value,
                },
            )
        )

        for event in stage_events:
            event_index += 1
            payload: dict[str, Any] = {
                "event_index": event_index,
                "attempt_count": run.attempt_count,
                "stage": event.stage.value,
                "transition": event.transition.value,
            }
            if event.error_code is not None:
                payload["error_code"] = event.error_code
            if event.message is not None:
                payload["message"] = event.message

            db.add(
                AuditLog(
                    run_id=run.id,
                    event_type="run_stage_transition",
                    actor="system:orchestrator",
                    payload_json=payload,
                )
            )

        event_index += 1
        status_payload: dict[str, Any] = {
            "event_index": event_index,
            "attempt_count": run.attempt_count,
            "from_status": RunStatus.PROCESSING.value,
            "to_status": final_status.value,
        }
        if final_status is RunStatus.FAILED:
            status_payload["failure_stage"] = failure_stage.value if failure_stage else None
            status_payload["error_code"] = failure_error_code

        db.add(
            AuditLog(
                run_id=run.id,
                event_type="run_status_transition",
                actor="system:orchestrator",
                payload_json=status_payload,
            )
        )

    def _set_stage_event_callback(self, callback: StageEventCallback | None) -> None:
        setter = getattr(self._executor, "set_stage_event_callback", None)
        if callable(setter):
            setter(callback)


def _build_finding_key(*, order: int, sort_key: str) -> str:
    digest = hashlib.sha256(sort_key.encode("utf-8")).hexdigest()
    return f"{order:06d}:{digest}"


def _count_breaking_findings(classified_findings: tuple[ClassifiedFinding, ...]) -> int:
    return sum(
        1
        for item in classified_findings
        if item.finding.compatibility is CompatibilityClassification.BREAKING
    )


__all__ = [
    "InProcessRunExecutor",
    "PipelineStage",
    "RunAlreadyCompletedError",
    "RunAlreadyProcessingError",
    "RunExecutor",
    "RunInvalidStateError",
    "RunNotFoundError",
    "RunOrchestrationService",
    "RunStageExecutionError",
]

