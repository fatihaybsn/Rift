"""add analysis run lifecycle metadata

Revision ID: 20260320_0002
Revises: 20260315_0001
Create Date: 2026-03-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260320_0002"
down_revision: str | None = "20260315_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("failure_stage", sa.String(length=64), nullable=True),
    )
    op.add_column("analysis_runs", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column(
        "analysis_runs",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE analysis_runs
        SET status = 'pending'
        WHERE status NOT IN ('pending', 'processing', 'completed', 'failed')
        """
    )
    op.create_check_constraint(
        "ck_analysis_runs_status",
        "analysis_runs",
        "status IN ('pending', 'processing', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_analysis_runs_attempt_count_non_negative",
        "analysis_runs",
        "attempt_count >= 0",
    )
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"], unique=False)

    op.alter_column("analysis_runs", "attempt_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_constraint("ck_analysis_runs_attempt_count_non_negative", "analysis_runs")
    op.drop_constraint("ck_analysis_runs_status", "analysis_runs")
    op.drop_column("analysis_runs", "failed_at")
    op.drop_column("analysis_runs", "error_code")
    op.drop_column("analysis_runs", "failure_stage")
    op.drop_column("analysis_runs", "processing_started_at")
    op.drop_column("analysis_runs", "locked_at")
    op.drop_column("analysis_runs", "attempt_count")
