"""Tests for the persistent scheduler worker."""

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
    """v0.2 worker contains only valuation-discovery pipeline jobs."""
    scheduler = build_scheduler(
        interval_seconds=300,
        indexing_job=lambda: None,
    )

    assert scheduler.get_job("holdings-monitoring") is None
    assert scheduler.get_job("document-indexing") is not None


def test_worker_builds_data_ingestion_stack(database_url, tmp_path):
    """worker builds data ingestion stack."""
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
    """Missing real embedding credentials must not create fake searchable data."""
    settings = MarginSettings(
        _env_file=None,
        database_url=database_url,
        embedding_api_key=None,
        embedding_base_url=None,
    )
    monkeypatch.setattr("margin.worker.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="MARGIN_SECRET_MASTER_KEY"):
        build_document_indexing_runner()


def test_worker_uses_versioned_provider_runtime_factory(
    database_url: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker adapters come from active config, not direct environment secrets."""
    class _Embedding:
        dim = 2048

    embedding = _Embedding()
    tushare = object()

    class _Runtime:
        def __init__(self, adapter, version_id: str) -> None:
            self.adapter = adapter
            self.config_version_id = version_id

    class _Factory:
        def build_embedding(self):
            """build_embedding."""
            return _Runtime(embedding, "provider-embedding-v1")

        def build_tushare(self):
            """build_tushare."""
            return _Runtime(tushare, "provider-tushare-v1")

        def build_akshare(self):
            """build_akshare."""
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
