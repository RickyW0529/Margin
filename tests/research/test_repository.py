"""Tests for append-only module 06 snapshot persistence."""

from __future__ import annotations

import pytest

from margin.research.models import WorkflowState
from margin.research.repository import MemoryResearchRepository
from margin.research.snapshot import ResearchSnapshotBuilder


def test_memory_repository_persists_terminal_snapshot() -> None:
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
