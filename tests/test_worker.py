"""Tests for the persistent scheduler worker.

Verifies that the v0.2 worker registers only valuation-discovery pipeline jobs,
builds a data ingestion stack, refuses hash embeddings without real credentials,
and uses the versioned provider runtime factory.
"""

from __future__ import annotations

import pytest

import margin.worker as worker_module
from margin.settings import MarginSettings
from margin.worker import (
    build_data_ingestion_stack,
    build_data_sync_worker,
    build_document_indexing_runner,
    build_scheduler,
)


def test_worker_does_not_register_holdings_monitoring_job():
    """Test that the v0.2 worker contains only valuation-discovery pipeline jobs."""
    scheduler = build_scheduler(
        interval_seconds=300,
        indexing_job=lambda: None,
    )

    assert scheduler.get_job("holdings-monitoring") is None
    assert scheduler.get_job("document-indexing") is not None


def test_worker_builds_data_ingestion_stack(database_url, tmp_path):
    """Test that the worker builds a data ingestion stack with a warehouse.

    Args:
        database_url: Connection string for the PostgreSQL test server.
        tmp_path: Pytest fixture providing a temporary directory.
    """
    settings = MarginSettings(
        _env_file=None,
        database_url=database_url,
        data_snapshot_root=tmp_path,
    )

    stack = build_data_ingestion_stack(settings)

    assert stack.warehouse is not None


def test_worker_refuses_hash_embedding_in_production_path(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that missing real embedding credentials do not create fake searchable data.

    Args:
        database_url: Connection string for the PostgreSQL test server.
        monkeypatch: Pytest fixture for modifying settings and environment.
    """
    settings = MarginSettings(
        _env_file=None,
        database_url=database_url,
    )
    monkeypatch.setattr("margin.worker.get_settings", lambda: settings)

    with pytest.raises(LookupError, match="active provider config not found"):
        build_document_indexing_runner()


def test_worker_uses_versioned_provider_runtime_factory(
    database_url: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that worker adapters come from active config, not direct environment secrets.

    Args:
        database_url: Connection string for the PostgreSQL test server.
        tmp_path: Pytest fixture providing a temporary directory.
        monkeypatch: Pytest fixture for patching module attributes.
    """
    class _Embedding:
        """Stub embedding provider with a fixed dimension."""

        dim = 2048

    embedding = _Embedding()
    tushare = object()

    class _Runtime:
        """Stub provider runtime holding an adapter and config version ID."""

        def __init__(self, adapter, version_id: str) -> None:
            """Initialize the runtime with an adapter and version ID."""
            self.adapter = adapter
            self.config_version_id = version_id

    class _Factory:
        """Stub factory that builds embedding and Tushare runtimes."""

        def build_embedding(self):
            """Build a stub embedding runtime."""
            return _Runtime(embedding, "provider-embedding-v1")

        def build_tushare(self):
            """Build a stub Tushare runtime."""
            return _Runtime(tushare, "provider-tushare-v1")

        def build_akshare(self):
            """Raise LookupError to simulate an inactive AKShare provider."""
            raise LookupError("not active")

    settings = MarginSettings(
        _env_file=None,
        database_url=database_url,
        data_snapshot_root=tmp_path,
        secret_master_key="a" * 32,
    )
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        worker_module,
        "build_worker_provider_runtime_factory",
        lambda _settings: _Factory(),
    )
    monkeypatch.setattr(
        worker_module,
        "DocumentIndexingRunner",
        lambda **kwargs: kwargs,
    )

    indexing = build_document_indexing_runner()
    sync_worker = build_data_sync_worker(settings)

    assert indexing["embedding_provider"] is embedding
    assert sync_worker.providers == {"tushare": tushare}
    assert sync_worker.provider_config_version_ids == {
        "tushare": "provider-tushare-v1"
    }
