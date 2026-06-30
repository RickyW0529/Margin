"""Tests for research domain models.

This module verifies that ``ResearchSignal`` defaults are applied correctly
and that workflow state and signal type enumerations expose the expected
string values.
"""

from __future__ import annotations

from margin.research.models import ResearchSignal, SignalType, WorkflowState


def test_research_signal_defaults():
    """Verify ``ResearchSignal`` applies correct default field values.

    Creates a signal with only the required fields and asserts that the
    confidence defaults to ``0.0`` and the evidence refs default to an empty
    tuple.
    """
    signal = ResearchSignal(symbol="000001.SZ", signal_type=SignalType.WATCH)
    assert signal.symbol == "000001.SZ"
    assert signal.signal_type == SignalType.WATCH
    assert signal.confidence == 0.0
    assert signal.evidence_refs == ()


def test_workflow_states_are_strings():
    """Verify workflow state and signal type enumerations use string values.

    Asserts that ``WorkflowState.PUBLISHED`` equals ``"published"`` and
    ``SignalType.RESEARCH_CANDIDATE`` equals ``"research_candidate"``.
    """
    assert WorkflowState.PUBLISHED == "published"
    assert SignalType.RESEARCH_CANDIDATE == "research_candidate"
