"""Migration smoke tests against a real PostgreSQL database."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from alembic import command
from tests.fixtures.postgres import (
    assert_safe_test_database,
    load_test_database_url,
    prepare_alembic_runtime,
    reset_target_schema,
)

EXPECTED_TABLES = {
    "analysis_runs",
    "audit_logs",
    "deterministic_findings",
    "migration_tasks",
    "normalized_snapshots",
    "spec_artifacts",
}
EXPECTED_ANALYSIS_RUN_COLUMNS = {
    "id",
    "status",
    "attempt_count",
    "locked_at",
    "processing_started_at",
    "requested_by",
    "failure_stage",
    "error_code",
    "failure_reason",
    "created_at",
    "updated_at",
    "failed_at",
    "completed_at",
    "llm_summary",
    "llm_migration_tasks",
    "llm_confidence",
    "llm_status",
    "llm_explanation",
    "llm_error_code",
    "llm_provider",
    "llm_model",
    "llm_completed_at",
}


def test_upgrade_head_creates_expected_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    test_database_url = load_test_database_url()
    assert_safe_test_database(sa.make_url(test_database_url))
    reset_target_schema(test_database_url)

    alembic_config = prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")

    engine = sa.create_engine(test_database_url)
    inspector = sa.inspect(engine)
    discovered_tables = set(inspector.get_table_names())
    analysis_run_columns = {column["name"] for column in inspector.get_columns("analysis_runs")}
    engine.dispose()

    assert EXPECTED_TABLES.issubset(discovered_tables)
    assert EXPECTED_ANALYSIS_RUN_COLUMNS.issubset(analysis_run_columns)


def test_downgrade_base_drops_expected_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    test_database_url = load_test_database_url()
    assert_safe_test_database(sa.make_url(test_database_url))
    reset_target_schema(test_database_url)

    alembic_config = prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = sa.create_engine(test_database_url)
    inspector = sa.inspect(engine)
    discovered_tables = set(inspector.get_table_names())
    engine.dispose()

    assert EXPECTED_TABLES.isdisjoint(discovered_tables)
