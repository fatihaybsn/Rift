"""Reusable PostgreSQL test helpers for migration/integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings
from app.db.session import reset_db_session_state

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = REPO_ROOT / "alembic"
TEST_DB_ENV_VAR = "TEST_POSTGRES_DATABASE_URL"


def load_test_database_url() -> str:
    test_database_url = os.getenv(TEST_DB_ENV_VAR)
    if not test_database_url:
        pytest.skip(f"{TEST_DB_ENV_VAR} is not set; skipping PostgreSQL-backed tests.")
    return test_database_url


def assert_safe_test_database(url: URL) -> None:
    database_name = (url.database or "").lower()
    if "test" not in database_name:
        msg = (
            "Refusing to run integration test on a non-test database. "
            f"Set {TEST_DB_ENV_VAR} to a database name containing 'test'."
        )
        raise RuntimeError(msg)


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def reset_target_schema(database_url: str) -> None:
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


def prepare_alembic_runtime(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_db_session_state()
    return build_alembic_config(database_url)


def parse_test_database_url() -> URL:
    return make_url(load_test_database_url())
