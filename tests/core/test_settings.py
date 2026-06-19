"""Tests for centralized MarginSettings.

Covers defaults, caching, secret masking, and the empty-string-to-None
normalization needed by Docker Compose interpolation.
"""

from __future__ import annotations

from margin.settings import MarginSettings, get_settings


def test_settings_reads_database_url():
    # _env_file=None keeps tests independent of any local .env file.
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
    # SecretStr must hide the raw value in repr() to avoid leaking keys in logs.
    assert "secret-key" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "secret-key"


def test_settings_treats_empty_optional_urls_as_unconfigured():
    settings = MarginSettings(
        _env_file=None,
        llm_base_url="",
        embedding_base_url="",
        rerank_base_url="",
    )

    assert settings.llm_base_url is None
    assert settings.embedding_base_url is None
    assert settings.rerank_base_url is None
