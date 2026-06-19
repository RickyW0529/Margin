"""Tests for local snapshot store."""

from __future__ import annotations

from margin.core.snapshot_store import FileSnapshotStore


def test_snapshot_store_writes_and_reads(tmp_path):
    store = FileSnapshotStore(base_path=tmp_path)
    entry = store.write(
        object_type="research_report",
        object_id="rep_1",
        payload={"summary": "buy"},
    )
    assert entry.sha256.startswith("sha256:")
    loaded = store.read(entry.snapshot_id)
    assert loaded.payload["summary"] == "buy"
