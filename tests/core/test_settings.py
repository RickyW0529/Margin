"""Tests for centralized MarginSettings.

Covers defaults, caching, secret masking, and the empty-string-to-None
normalization needed by Docker Compose interpolation.
"""

from __future__ import annotations

from pathlib import Path

from margin.settings import MarginSettings, get_settings


def test_settings_reads_database_url():
    # _env_file=None keeps tests independent of any local .env file.
    settings = MarginSettings(_env_file=None)
    assert "postgresql" in str(settings.database_url)
    assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_settings_default_llm_model_is_deepseek_pro():
    settings = MarginSettings(_env_file=None)
    assert settings.llm_model == "deepseek-v4-pro"


def test_settings_default_audit_log_path_is_project_relative():
    settings = MarginSettings(_env_file=None)
    assert settings.audit_log_path == Path(".margin/audit/provider_calls.jsonl")
    assert not settings.audit_log_path.is_absolute()


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
