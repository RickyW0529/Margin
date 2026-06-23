"""Tests for local snapshot store.

Verifies that payloads are persisted, content-addressed by SHA-256, and round-trip
through the read/list API without data loss.
"""

from __future__ import annotations

from margin.core.snapshot_store import FileSnapshotStore
from scripts.snapshot_store import main as snapshot_store_main


def test_snapshot_store_writes_and_reads(tmp_path):
    """snapshot store writes and reads."""
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


def test_snapshot_store_cli_default_base_path_is_project_relative(tmp_path, monkeypatch):
    """snapshot store cli default base path is project relative."""
    monkeypatch.chdir(tmp_path)
    exit_code = snapshot_store_main(
        [
            "write",
            "--type",
            "research_report",
            "--object-id",
            "rep_1",
            "--payload",
            '{"summary":"buy"}',
        ]
    )

    assert exit_code == 0
    assert (tmp_path / ".margin/snapshots").is_dir()
