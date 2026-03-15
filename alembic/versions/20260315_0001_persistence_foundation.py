"""create persistence foundation schema

Revision ID: 20260315_0001
Revises:
Create Date: 2026-03-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260315_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "spec_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "old_spec",
                "new_spec",
                "changelog_text",
                name="artifact_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("payload_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "byte_size >= 0",
            name="ck_spec_artifacts_non_negative_size",
        ),
        sa.CheckConstraint(
            "(payload_bytes IS NOT NULL) <> (payload_text IS NOT NULL)",
            name="ck_spec_artifacts_exactly_one_payload",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "kind", name="uq_spec_artifacts_run_kind"),
    )
    op.create_index("ix_spec_artifacts_run_id", "spec_artifacts", ["run_id"], unique=False)

    op.create_table(
        "normalized_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "old",
                "new",
                name="snapshot_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["spec_artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "kind", name="uq_normalized_snapshots_run_kind"),
    )
    op.create_index(
        "ix_normalized_snapshots_run_id",
        "normalized_snapshots",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "deterministic_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_key", sa.String(length=128), nullable=False),
        sa.Column("finding_order", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("location", sa.String(length=512), nullable=False),
        sa.Column("http_method", sa.String(length=16), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "finding_key", name="uq_deterministic_findings_run_key"),
        sa.UniqueConstraint("run_id", "finding_order", name="uq_deterministic_findings_run_order"),
    )
    op.create_index(
        "ix_deterministic_findings_run_id",
        "deterministic_findings",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_deterministic_findings_run_severity",
        "deterministic_findings",
        ["run_id", "severity"],
        unique=False,
    )

    op.create_table(
        "migration_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("priority >= 0", name="ck_migration_tasks_non_negative_priority"),
        sa.ForeignKeyConstraint(["finding_id"], ["deterministic_findings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_migration_tasks_run_id", "migration_tasks", ["run_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_run_id", "audit_logs", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_run_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_migration_tasks_run_id", table_name="migration_tasks")
    op.drop_table("migration_tasks")

    op.drop_index("ix_deterministic_findings_run_severity", table_name="deterministic_findings")
    op.drop_index("ix_deterministic_findings_run_id", table_name="deterministic_findings")
    op.drop_table("deterministic_findings")

    op.drop_index("ix_normalized_snapshots_run_id", table_name="normalized_snapshots")
    op.drop_table("normalized_snapshots")

    op.drop_index("ix_spec_artifacts_run_id", table_name="spec_artifacts")
    op.drop_table("spec_artifacts")

    op.drop_table("analysis_runs")
