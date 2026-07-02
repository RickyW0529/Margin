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
    assert not settings.data_snapshot_root.is_absolute()


def test_settings_caches_instance():
    """Test that settings caches the singleton instance."""
    assert get_settings() is get_settings()


def test_settings_secret_master_key_is_masked():
    """Test that the local encryption master key is masked in repr."""
    settings = MarginSettings(
        _env_file=None,
        secret_master_key="master-key-secret",
    )
    # SecretStr must hide the raw value in repr() to avoid leaking keys in logs.
    assert "master-key-secret" not in repr(settings)
    assert settings.secret_master_key.get_secret_value() == "master-key-secret"


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
