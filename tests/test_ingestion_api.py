"""Tests for run-ingestion API behavior."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.api.v1.runs import MAX_CHANGELOG_TEXT_BYTES, MAX_SPEC_BYTES
from app.core.config import Settings, get_settings
from app.db import AnalysisRun, ArtifactKind, SpecArtifact, get_db_session
from app.db.session import reset_db_session_state
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = REPO_ROOT / "alembic"
TEST_DB_ENV_VAR = "TEST_POSTGRES_DATABASE_URL"


class FakeSession:
    """Minimal session stub for API-level request validation tests."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _build_client_with_fake_session(fake_session: FakeSession) -> TestClient:
    app = create_app()

    def override_get_db_session():
        yield fake_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app)


def _build_valid_spec_yaml(title: str) -> bytes:
    return (f"openapi: 3.0.3\ninfo:\n  title: {title}\n  version: 1.0.0\npaths: {{}}\n").encode()


def _build_specs_payload(
    media_type: str = "application/yaml",
) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("specs", ("old.yaml", _build_valid_spec_yaml("Old API"), media_type)),
        ("specs", ("new.yaml", _build_valid_spec_yaml("New API"), media_type)),
    ]


def _load_test_database_url() -> str:
    test_database_url = os.getenv(TEST_DB_ENV_VAR)
    if not test_database_url:
        pytest.skip(f"{TEST_DB_ENV_VAR} is not set; skipping integration persistence test.")
    return test_database_url


def _assert_safe_test_database(url: URL) -> None:
    database_name = (url.database or "").lower()
    if "test" not in database_name:
        msg = (
            "Refusing to run integration test on a non-test database. "
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


def test_create_analysis_run_happy_path_persists_expected_artifacts_with_fake_session() -> None:
    fake_session = FakeSession()
    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=_build_specs_payload(),
            data={"changelog_text": "Renamed /pets response field."},
        )

    assert response.status_code == 201
    body = response.json()
    UUID(body["run_id"])
    assert body["status"] == "pending"
    assert fake_session.committed is True
    assert fake_session.rolled_back is False

    run_records = [obj for obj in fake_session.added if isinstance(obj, AnalysisRun)]
    artifact_records = [obj for obj in fake_session.added if isinstance(obj, SpecArtifact)]

    assert len(run_records) == 1
    assert len(artifact_records) == 3
    assert [artifact.kind for artifact in artifact_records] == [
        ArtifactKind.OLD_SPEC,
        ArtifactKind.NEW_SPEC,
        ArtifactKind.CHANGELOG_TEXT,
    ]


def test_create_analysis_run_rejects_when_spec_count_is_not_exactly_two() -> None:
    fake_session = FakeSession()
    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=[("specs", ("old.yaml", _build_valid_spec_yaml("Old API"), "application/yaml"))],
        )

    assert response.status_code == 400
    assert "Exactly two spec files" in response.json()["detail"]
    assert fake_session.committed is False


def test_create_analysis_run_rejects_unsupported_spec_content_type() -> None:
    fake_session = FakeSession()
    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=_build_specs_payload(media_type="text/plain"),
        )

    assert response.status_code == 415
    assert "Unsupported spec content type" in response.json()["detail"]
    assert fake_session.committed is False
    assert fake_session.rolled_back is True


def test_create_analysis_run_rejects_empty_spec_file() -> None:
    fake_session = FakeSession()
    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=[
                ("specs", ("old.yaml", b"", "application/yaml")),
                ("specs", ("new.yaml", _build_valid_spec_yaml("New API"), "application/yaml")),
            ],
        )

    assert response.status_code == 422
    assert "must not be empty" in response.json()["detail"]
    assert fake_session.committed is False
    assert fake_session.rolled_back is True


def test_create_analysis_run_rejects_spec_larger_than_limit() -> None:
    fake_session = FakeSession()
    oversized_content = b"a" * (MAX_SPEC_BYTES + 1)

    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=[
                ("specs", ("old.yaml", oversized_content, "application/yaml")),
                ("specs", ("new.yaml", _build_valid_spec_yaml("New API"), "application/yaml")),
            ],
        )

    assert response.status_code == 413
    assert "byte limit" in response.json()["detail"]
    assert fake_session.committed is False
    assert fake_session.rolled_back is True


def test_create_analysis_run_rejects_oversized_changelog_text() -> None:
    fake_session = FakeSession()
    oversized_changelog = "a" * (MAX_CHANGELOG_TEXT_BYTES + 1)

    with _build_client_with_fake_session(fake_session) as client:
        response = client.post(
            f"{Settings().api_prefix}/runs",
            files=_build_specs_payload(),
            data={"changelog_text": oversized_changelog},
        )

    assert response.status_code == 413
    assert "changelog_text exceeds" in response.json()["detail"]
    assert fake_session.committed is False
    assert fake_session.rolled_back is True


def test_create_analysis_run_integration_persists_run_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_database_url = _load_test_database_url()
    parsed_url = make_url(test_database_url)
    _assert_safe_test_database(parsed_url)
    _reset_target_schema(test_database_url)

    alembic_config = _prepare_alembic_runtime(monkeypatch, test_database_url)
    command.upgrade(alembic_config, "head")

    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.post(
                f"{Settings().api_prefix}/runs",
                files=_build_specs_payload(),
                data={"changelog_text": "Documented breaking change."},
            )

        assert response.status_code == 201
        payload = response.json()
        run_id = payload["run_id"]
        assert payload["status"] == "pending"

        engine = sa.create_engine(test_database_url)
        try:
            with engine.connect() as connection:
                run_row = (
                    connection.execute(
                        sa.text(
                            """
                        SELECT id, status
                        FROM analysis_runs
                        WHERE id = :run_id
                        """
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .one()
                )

                artifact_rows = (
                    connection.execute(
                        sa.text(
                            """
                        SELECT kind, media_type, byte_size
                        FROM spec_artifacts
                        WHERE run_id = :run_id
                        ORDER BY kind
                        """
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                )
        finally:
            engine.dispose()

        assert str(run_row["id"]) == run_id
        assert run_row["status"] == "pending"
        assert len(artifact_rows) == 3
        assert [row["kind"] for row in artifact_rows] == [
            "changelog_text",
            "new_spec",
            "old_spec",
        ]
    finally:
        command.downgrade(alembic_config, "base")
        reset_db_session_state()
        get_settings.cache_clear()
