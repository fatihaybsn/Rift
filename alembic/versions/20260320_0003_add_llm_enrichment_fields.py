"""add llm enrichment fields to analysis runs

Revision ID: 20260320_0003
Revises: 20260320_0002
Create Date: 2026-03-20 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260320_0003"
down_revision: str | None = "20260320_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("llm_summary", sa.Text(), nullable=True))
    op.add_column(
        "analysis_runs",
        sa.Column("llm_migration_tasks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("analysis_runs", sa.Column("llm_confidence", sa.Float(), nullable=True))
    op.add_column(
        "analysis_runs",
        sa.Column(
            "llm_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'not_requested'"),
        ),
    )
    op.add_column("analysis_runs", sa.Column("llm_explanation", sa.Text(), nullable=True))
    op.add_column("analysis_runs", sa.Column("llm_error_code", sa.String(length=64), nullable=True))
    op.add_column("analysis_runs", sa.Column("llm_provider", sa.String(length=64), nullable=True))
    op.add_column("analysis_runs", sa.Column("llm_model", sa.String(length=128), nullable=True))
    op.add_column(
        "analysis_runs",
        sa.Column("llm_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_analysis_runs_llm_status",
        "analysis_runs",
        (
            "llm_status IN ("
            "'not_requested', "
            "'disabled', "
            "'pending', "
            "'completed', "
            "'manual_review_required', "
            "'failed'"
            ")"
        ),
    )
    op.alter_column("analysis_runs", "llm_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_analysis_runs_llm_status", "analysis_runs")
    op.drop_column("analysis_runs", "llm_completed_at")
    op.drop_column("analysis_runs", "llm_model")
    op.drop_column("analysis_runs", "llm_provider")
    op.drop_column("analysis_runs", "llm_error_code")
    op.drop_column("analysis_runs", "llm_status")
    op.drop_column("analysis_runs", "llm_confidence")
    op.drop_column("analysis_runs", "llm_explanation")
    op.drop_column("analysis_runs", "llm_migration_tasks")
    op.drop_column("analysis_runs", "llm_summary")
