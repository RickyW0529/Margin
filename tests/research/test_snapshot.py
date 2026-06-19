"""Tests for research snapshot builder."""

from __future__ import annotations

import json

from margin.research.models import ResearchSignal, SignalType, WorkflowState
from margin.research.snapshot import ResearchSnapshotBuilder


def test_snapshot_hashes_inputs_and_outputs():
    signal = ResearchSignal(symbol="000001.SZ", signal_type=SignalType.WATCH, confidence=0.5)
    builder = ResearchSnapshotBuilder()
    snapshot = (
        builder.for_run("run_1")
        .with_state(WorkflowState.PUBLISHED)
        .with_symbols(["000001.SZ"])
        .with_signals([signal])
        .with_prior_outputs({"foo": "bar"})
        .build()
    )
    assert snapshot.run_id == "run_1"
    assert snapshot.input_hash != ""
    assert snapshot.output_hash != ""
    assert snapshot.workflow_state == WorkflowState.PUBLISHED
    assert json.loads(snapshot.agent_outputs_json) == {"foo": "bar"}


def test_snapshot_is_frozen():
    snapshot = ResearchSnapshotBuilder().for_run("run_2").with_state(WorkflowState.ABORTED).build()
    # Pydantic frozen model should reject mutation attempts
    try:
        snapshot.run_id = "changed"  # type: ignore[misc]
        assert False, "expected frozen model to reject mutation"
    except Exception:
        pass
