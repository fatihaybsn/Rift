"""Settings loading behavior tests."""

import pytest

from app.core.config import Settings


def test_database_url_default_is_role_agnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default DB URL should not hardcode postgres role credentials."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://localhost:5432/api_change_radar"


def test_database_url_reads_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL environment variable should override defaults."""
    custom_url = "postgresql+psycopg://app_user:secret@localhost:5432/api_change_radar"
    monkeypatch.setenv("DATABASE_URL", custom_url)
    settings = Settings(_env_file=None)
    assert settings.database_url == custom_url


def test_llm_feature_flags_have_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_LLM_CHANGELOG", raising=False)
    monkeypatch.delenv("LLM_CHANGELOG_INTERPRETER_ENABLED", raising=False)
    monkeypatch.delenv("LLM_LOW_CONFIDENCE_THRESHOLD", raising=False)

    settings = Settings(_env_file=None)
    assert settings.llm_changelog_interpreter_enabled is False
    assert settings.llm_low_confidence_threshold == 0.6


def test_llm_feature_flag_reads_canonical_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_CHANGELOG", "true")
    monkeypatch.delenv("LLM_CHANGELOG_INTERPRETER_ENABLED", raising=False)

    settings = Settings(_env_file=None)
    assert settings.llm_changelog_interpreter_enabled is True


def test_llm_feature_flag_supports_legacy_alias_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_LLM_CHANGELOG", raising=False)
    monkeypatch.setenv("LLM_CHANGELOG_INTERPRETER_ENABLED", "true")

    settings = Settings(_env_file=None)
    assert settings.llm_changelog_interpreter_enabled is True
