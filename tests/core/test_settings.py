"""Tests for centralized MarginSettings.

Covers defaults, caching, secret masking, and the empty-string-to-None
normalization needed by Docker Compose interpolation.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from margin.settings import MarginSettings, get_settings


def test_settings_reads_database_url():
    # _env_file=None keeps tests independent of any local .env file.
    """Test that settings reads the database URL from configuration."""
    settings = MarginSettings(_env_file=None)
    assert "postgresql" in str(settings.database_url)
    assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_settings_default_llm_model_is_deepseek_pro():
    """Test that the default LLM model is deepseek-v4-pro."""
    settings = MarginSettings(_env_file=None)
    assert settings.llm_model == "deepseek-v4-pro"


def test_settings_default_audit_log_path_is_project_relative():
    """Test that the default audit log path is project-relative."""
    settings = MarginSettings(_env_file=None)
    assert settings.audit_log_path == Path(".margin/audit/provider_calls.jsonl")
    assert not settings.audit_log_path.is_absolute()


def test_settings_default_data_snapshot_root_is_project_relative():
    """Test that the default data snapshot root is project-relative."""
    settings = MarginSettings(_env_file=None)
    assert settings.data_snapshot_root == Path(".margin/snapshots/data")
    assert settings.data_sync_on_startup is True
    assert settings.tushare_http_url is None
    assert not settings.data_snapshot_root.is_absolute()


def test_settings_caches_instance():
    """Test that settings caches the singleton instance."""
    assert get_settings() is get_settings()


def test_settings_secrets_are_masked():
    """Test that secret fields are masked in repr to avoid leaking keys."""
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="secret-key",
        tushare_token="tushare-secret",
        admin_api_token="admin-secret",
        csrf_token="csrf-secret",
        secret_master_key="master-key-secret",
    )
    # SecretStr must hide the raw value in repr() to avoid leaking keys in logs.
    assert "secret-key" not in repr(settings)
    assert "tushare-secret" not in repr(settings)
    assert "admin-secret" not in repr(settings)
    assert "csrf-secret" not in repr(settings)
    assert "master-key-secret" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "secret-key"
    assert settings.tushare_token.get_secret_value() == "tushare-secret"


def test_settings_treats_empty_optional_urls_as_unconfigured():
    """Test that empty optional URLs are treated as unconfigured (None)."""
    settings = MarginSettings(
        _env_file=None,
        llm_base_url="",
        embedding_base_url="",
        rerank_base_url="",
    )

    assert settings.llm_base_url is None
    assert settings.embedding_base_url is None
    assert settings.rerank_base_url is None


def test_settings_exposes_versioned_capacity_defaults() -> None:
    """Test that settings exposes versioned capacity defaults."""
    settings = MarginSettings(_env_file=None)

    assert settings.capacity_limit_version == "limits-v0.2.0"
    assert settings.worker_max_concurrency > 0
    assert settings.graph_max_concurrency > 0
    assert settings.provider_default_rpm > 0
    assert settings.provider_default_tpm > 0
    assert settings.llm_daily_token_budget > 0
    assert settings.llm_daily_cost_budget == Decimal("20.00")
    assert settings.news_target_queue_high_water > 0
    assert settings.embedding_batch_size > 0
    assert settings.database_statement_timeout_ms > 0


def test_settings_rejects_non_positive_capacity_values() -> None:
    """Test that settings rejects non-positive capacity values."""
    with pytest.raises(ValidationError):
        MarginSettings(_env_file=None, worker_max_concurrency=0)
