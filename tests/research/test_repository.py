"""Tests for append-only module 06 snapshot persistence.

This module verifies that the in-memory research repository correctly
persists terminal snapshots and rejects attempts to mutate an already-stored
immutable snapshot.
"""

from __future__ import annotations

import pytest

from margin.research.models import WorkflowState
from margin.research.repository import MemoryResearchRepository
from margin.research.snapshot import ResearchSnapshotBuilder


def test_memory_repository_persists_terminal_snapshot() -> None:
    """Verify the memory repository persists and retrieves a terminal snapshot.

    Builds a snapshot with an aborted state and error, adds it to the
    repository, and asserts that it can be retrieved by both snapshot ID and
    run ID.
    """
    repository = MemoryResearchRepository()
    snapshot = (
        ResearchSnapshotBuilder()
        .for_run("run-1")
        .with_state(WorkflowState.ABSTAINED)
        .with_error("insufficient evidence")
        .build()
    )

    repository.add_snapshot(snapshot)

    assert repository.get_snapshot(snapshot.snapshot_id) == snapshot
    assert repository.get_snapshot_for_run("run-1") == snapshot


def test_memory_repository_rejects_snapshot_mutation() -> None:
    """Verify the memory repository rejects mutations to an immutable snapshot.

    Adds a snapshot to the repository, creates a copy with a changed output
    hash, and asserts that adding the mutated copy raises a ``ValueError``
    mentioning immutability.
    """
    repository = MemoryResearchRepository()
    snapshot = (
        ResearchSnapshotBuilder()
        .for_run("run-1")
        .with_state(WorkflowState.ABSTAINED)
        .build()
    )
    repository.add_snapshot(snapshot)
    changed = snapshot.model_copy(update={"output_hash": "changed"})

    with pytest.raises(ValueError, match="immutable"):
        repository.add_snapshot(changed)
