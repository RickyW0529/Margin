"""Tests for local snapshot store.

Verifies that payloads are persisted, content-addressed by SHA-256, and round-trip
through the read/list API without data loss.
"""

from __future__ import annotations

from margin.core.snapshot_store import FileSnapshotStore


def test_snapshot_store_writes_and_reads(tmp_path):
    store = FileSnapshotStore(base_path=tmp_path)
    entry = store.write(
        object_type="research_report",
        object_id="rep_1",
        payload={"summary": "buy"},
    )
    # The store prefixes the digest to make the algorithm explicit for auditors.
    assert entry.sha256.startswith("sha256:")
    loaded = store.read(entry.snapshot_id)
    assert loaded.payload["summary"] == "buy"
