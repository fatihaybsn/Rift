"""Reusable real-PostgreSQL fixture for integration and smoke tests."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from tests.fixtures.postgres import (
    assert_safe_test_database,
    load_test_database_url,
    prepare_alembic_runtime,
    reset_target_schema,
)


@pytest.fixture()
def integration_db(monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    test_database_url = load_test_database_url()
    assert_safe_test_database(sa.make_url(test_database_url))
    reset_target_schema(test_database_url)
    alembic_config = prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(test_database_url)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield session_factory
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
