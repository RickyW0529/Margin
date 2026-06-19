"""Tests for research domain models."""

from __future__ import annotations

from margin.research.models import ResearchSignal, SignalType, WorkflowState


def test_research_signal_defaults():
    signal = ResearchSignal(symbol="000001.SZ", signal_type=SignalType.WATCH)
    assert signal.symbol == "000001.SZ"
    assert signal.signal_type == SignalType.WATCH
    assert signal.confidence == 0.0
    assert signal.evidence_refs == ()


def test_workflow_states_are_strings():
    assert WorkflowState.PUBLISHED == "published"
    assert SignalType.RESEARCH_CANDIDATE == "research_candidate"
