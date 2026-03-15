"""Persistence models for API Change Radar report store."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ArtifactKind(StrEnum):
    """Supported raw artifact roles within a run."""

    OLD_SPEC = "old_spec"
    NEW_SPEC = "new_spec"
    CHANGELOG_TEXT = "changelog_text"


class SnapshotKind(StrEnum):
    """Normalized snapshot side used by deterministic diffing."""

    OLD = "old"
    NEW = "new"


class AnalysisRun(Base):
    """Top-level analysis run metadata."""

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    spec_artifacts: Mapped[list[SpecArtifact]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    normalized_snapshots: Mapped[list[NormalizedSnapshot]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    deterministic_findings: Mapped[list[DeterministicFinding]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    migration_tasks: Mapped[list[MigrationTask]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class SpecArtifact(Base):
    """Raw uploaded artifact associated with an analysis run."""

    __tablename__ = "spec_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", name="uq_spec_artifacts_run_kind"),
        CheckConstraint("byte_size >= 0", name="ck_spec_artifacts_non_negative_size"),
        CheckConstraint(
            "(payload_bytes IS NOT NULL) <> (payload_text IS NOT NULL)",
            name="ck_spec_artifacts_exactly_one_payload",
        ),
        Index("ix_spec_artifacts_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ArtifactKind] = mapped_column(
        Enum(
            ArtifactKind,
            name="artifact_kind",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        nullable=False,
    )
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="spec_artifacts")
    normalized_snapshots: Mapped[list[NormalizedSnapshot]] = relationship(
        back_populates="source_artifact",
    )


class NormalizedSnapshot(Base):
    """Canonical normalized representation of each side (old/new)."""

    __tablename__ = "normalized_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", name="uq_normalized_snapshots_run_kind"),
        Index("ix_normalized_snapshots_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("spec_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[SnapshotKind] = mapped_column(
        Enum(
            SnapshotKind,
            name="snapshot_kind",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="normalized_snapshots")
    source_artifact: Mapped[SpecArtifact] = relationship(back_populates="normalized_snapshots")


class DeterministicFinding(Base):
    """Authoritative deterministic finding generated by diff + severity engines."""

    __tablename__ = "deterministic_findings"
    __table_args__ = (
        UniqueConstraint("run_id", "finding_key", name="uq_deterministic_findings_run_key"),
        UniqueConstraint("run_id", "finding_order", name="uq_deterministic_findings_run_order"),
        Index("ix_deterministic_findings_run_id", "run_id"),
        Index("ix_deterministic_findings_run_severity", "run_id", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_key: Mapped[str] = mapped_column(String(128), nullable=False)
    finding_order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    location: Mapped[str] = mapped_column(String(512), nullable=False)
    http_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="deterministic_findings")
    migration_tasks: Mapped[list[MigrationTask]] = relationship(back_populates="finding")


class MigrationTask(Base):
    """Optional migration guidance task associated with a run or finding."""

    __tablename__ = "migration_tasks"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_migration_tasks_non_negative_priority"),
        Index("ix_migration_tasks_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deterministic_findings.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="migration_tasks")
    finding: Mapped[DeterministicFinding | None] = relationship(back_populates="migration_tasks")


class AuditLog(Base):
    """Audit-style event records for run lifecycle and system actions."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[AnalysisRun | None] = relationship(back_populates="audit_logs")
