"""Raw payload snapshot and schema discovery tests."""

from __future__ import annotations

from margin.core.snapshot_store import CompressedSnapshotStore
from margin.data.schema_discovery import SchemaDiscoveryService


def test_same_payload_reuses_content_object(tmp_path) -> None:
    """same payload reuses content object."""
    store = CompressedSnapshotStore(tmp_path)

    first = store.write_json("akshare", {"x": 1})
    second = store.write_json("akshare", {"x": 1})

    assert first.storage_uri == second.storage_uri
    assert first.payload_hash == second.payload_hash
    assert first.compression == "zstd"


def test_missing_field_requires_consecutive_observations() -> None:
    """missing field requires consecutive observations."""
    state = SchemaDiscoveryService(missing_threshold=3)

    state.observe("daily_bar", {"a": 1})
    for _ in range(2):
        state.observe("daily_bar", {})

    assert state.field("daily_bar", "a").status == "active"


def test_field_becomes_missing_after_threshold() -> None:
    """field becomes missing after threshold."""
    state = SchemaDiscoveryService(missing_threshold=3)

    state.observe("daily_bar", {"a": 1})
    for _ in range(3):
        state.observe("daily_bar", {})

    assert state.field("daily_bar", "a").status == "missing"
