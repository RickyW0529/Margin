"""Tests for centralized MarginSettings."""

from __future__ import annotations

from margin.settings import MarginSettings, get_settings


def test_settings_reads_database_url():
    settings = MarginSettings(_env_file=None)
    assert "postgresql" in str(settings.database_url)
    assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_settings_caches_instance():
    assert get_settings() is get_settings()


def test_settings_secrets_are_masked():
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="secret-key",
    )
    assert "secret-key" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "secret-key"
