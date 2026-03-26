"""Migration smoke tests against a real PostgreSQL database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.core.config import get_settings
from app.db.session import reset_db_session_state

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = REPO_ROOT / "alembic"
TEST_DB_ENV_VAR = "TEST_POSTGRES_DATABASE_URL"

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
}


def _load_test_database_url() -> str:
    test_database_url = os.getenv(TEST_DB_ENV_VAR)
    if not test_database_url:
        pytest.skip(f"{TEST_DB_ENV_VAR} is not set; skipping PostgreSQL migration tests.")
    return test_database_url


def _assert_safe_test_database(url: URL) -> None:
    database_name = (url.database or "").lower()
    if "test" not in database_name:
        msg = (
            "Refusing to run migration tests on a non-test database. "
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


def test_upgrade_head_creates_expected_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    test_database_url = _load_test_database_url()
    parsed_url = make_url(test_database_url)
    _assert_safe_test_database(parsed_url)
    _reset_target_schema(test_database_url)

    alembic_config = _prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")

    engine = sa.create_engine(test_database_url)
    inspector = sa.inspect(engine)
    discovered_tables = set(inspector.get_table_names())
    analysis_run_columns = {column["name"] for column in inspector.get_columns("analysis_runs")}
    engine.dispose()

    assert EXPECTED_TABLES.issubset(discovered_tables)
    assert EXPECTED_ANALYSIS_RUN_COLUMNS.issubset(analysis_run_columns)


def test_downgrade_base_drops_expected_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    test_database_url = _load_test_database_url()
    parsed_url = make_url(test_database_url)
    _assert_safe_test_database(parsed_url)
    _reset_target_schema(test_database_url)

    alembic_config = _prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = sa.create_engine(test_database_url)
    inspector = sa.inspect(engine)
    discovered_tables = set(inspector.get_table_names())
    engine.dispose()

    assert EXPECTED_TABLES.isdisjoint(discovered_tables)
