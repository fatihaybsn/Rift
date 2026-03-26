"""Run orchestration service for deterministic analysis lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.diff_engine import diff_canonical_snapshots
from app.core.openapi_processing import (
    OpenAPIProcessingError,
    normalize_openapi_document,
    parse_openapi_document,
    validate_openapi_document,
)
from app.core.severity_engine import ClassifiedFinding, classify_findings
from app.db import (
    AnalysisRun,
    ArtifactKind,
    DeterministicFinding,
    NormalizedSnapshot,
    RunStatus,
    SnapshotKind,
    SpecArtifact,
)


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


@dataclass(frozen=True)
class ExecutionPayload:
    """Executor output passed to persistence stage."""

    old_artifact: SpecArtifact
    new_artifact: SpecArtifact
    old_snapshot: object
    new_snapshot: object
    classified_findings: tuple[ClassifiedFinding, ...]


class RunExecutor(Protocol):
    """Narrow seam for alternative execution mechanisms."""

    def execute(self, *, db: Session, run: AnalysisRun) -> ExecutionPayload:
        """Execute deterministic stages up to persisted payload generation."""


class InProcessRunExecutor:
    """Default synchronous, in-process execution strategy for MVP reliability."""

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
        try:
            return func(**kwargs)  # type: ignore[misc]
        except RunStageExecutionError:
            raise
        except OpenAPIProcessingError as exc:
            raise RunStageExecutionError(
                stage=stage,
                error_code=error_code,
                message=str(exc),
            ) from exc
        except Exception as exc:
            raise RunStageExecutionError(
                stage=stage,
                error_code=error_code,
                message=str(exc),
            ) from exc


class RunOrchestrationService:
    """Application service orchestrating run lifecycle transitions."""

    def __init__(self, *, executor: RunExecutor | None = None) -> None:
        self._executor = executor or InProcessRunExecutor()

    def process_run(self, *, db: Session, run_id: uuid.UUID) -> AnalysisRun:
        """Process one run synchronously from pending to completed/failed."""
        self._claim_pending_run(db=db, run_id=run_id)
        run = db.get(AnalysisRun, run_id)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} was not found after claim.")

        try:
            payload = self._executor.execute(db=db, run=run)
            self._persist_results(db=db, run=run, payload=payload)
            run.status = RunStatus.COMPLETED.value
            run.completed_at = datetime.now(tz=UTC)
            run.locked_at = None
            run.failed_at = None
            run.failure_stage = None
            run.error_code = None
            run.failure_reason = None
            db.commit()
            db.refresh(run)
            return run
        except RunStageExecutionError as exc:
            db.rollback()
            self._mark_failed(
                db=db,
                run_id=run_id,
                stage=exc.stage,
                error_code=exc.error_code,
                reason=str(exc),
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
            )
            raise fallback_error from exc

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
                    schema_version=payload.old_snapshot.schema_version,  # type: ignore[attr-defined]
                    content_json=payload.old_snapshot.to_dict(),  # type: ignore[attr-defined]
                    checksum=payload.old_snapshot.checksum(),  # type: ignore[attr-defined]
                )
            )
            db.add(
                NormalizedSnapshot(
                    run_id=run.id,
                    source_artifact=payload.new_artifact,
                    kind=SnapshotKind.NEW,
                    schema_version=payload.new_snapshot.schema_version,  # type: ignore[attr-defined]
                    content_json=payload.new_snapshot.to_dict(),  # type: ignore[attr-defined]
                    checksum=payload.new_snapshot.checksum(),  # type: ignore[attr-defined]
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

    def _mark_failed(
        self,
        *,
        db: Session,
        run_id: uuid.UUID,
        stage: PipelineStage,
        error_code: str,
        reason: str,
    ) -> None:
        db.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(
                status=RunStatus.FAILED.value,
                locked_at=None,
                failed_at=func.now(),
                failure_stage=stage.value,
                error_code=error_code,
                failure_reason=reason,
            )
        )
        db.commit()


def _build_finding_key(*, order: int, sort_key: str) -> str:
    digest = hashlib.sha256(sort_key.encode("utf-8")).hexdigest()
    return f"{order:06d}:{digest}"


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

