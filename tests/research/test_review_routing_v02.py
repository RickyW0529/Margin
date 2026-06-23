"""Deterministic v0.2 ReviewMode routing tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.research.graph.nodes.context import (
    CarryForwardRuleNode,
    ChangeSetBuilderNode,
    ContextPrecheckNode,
    GraphContextSnapshot,
)
from margin.research.graph.state import ReviewMode, create_initial_state

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_no_previous_assessment_routes_full_review() -> None:
    """no previous assessment routes full review."""
    state = _state(previous=None)
    context = _context()

    state = ContextPrecheckNode(context).run(state)
    state = ChangeSetBuilderNode(context).run(state)

    assert state.review_mode == ReviewMode.FULL_REVIEW


def test_news_incomplete_routes_review_deferred() -> None:
    """news incomplete routes review deferred."""
    state = _state(previous="assess-old")
    context = _context(news_target_complete=False)

    state = ContextPrecheckNode(context).run(state)

    assert state.review_mode == ReviewMode.REVIEW_DEFERRED
    assert state.effective_assessment_id == "assess-old"
    assert state.stale_reason == "news_target_incomplete"


def test_invalid_pit_routes_abstain() -> None:
    """invalid pit routes abstain."""
    state = ContextPrecheckNode(_context(pit_valid=False)).run(
        _state(previous="assess-old")
    )

    assert state.review_mode == ReviewMode.ABSTAIN
    assert state.effective_assessment_id == "assess-old"
    assert state.stale_reason == "context_pit_invalid"


def test_material_change_routes_delta_review() -> None:
    """material change routes delta review."""
    state = _state(previous="assess-old")
    context = _context(material_news_change=True)

    state = ContextPrecheckNode(context).run(state)
    state = ChangeSetBuilderNode(context).run(state)

    assert state.review_mode == ReviewMode.DELTA_REVIEW
    assert state.change_set["material_news_change"] is True


def test_identical_inputs_and_complete_news_routes_carry_forward() -> None:
    """identical inputs and complete news routes carry forward."""
    state = CarryForwardRuleNode(_context()).run(_state(previous="assess-old"))

    assert state.review_mode == ReviewMode.CARRY_FORWARD_FAST_PATH
    assert state.llm_call_count == 0
    assert state.effective_assessment_id == "assess-old"


def _state(*, previous: str | None):
    """state."""
    return create_initial_state(
        graph_run_id="graph-1",
        context_snapshot_id="ctx-1",
        context_input_hash="sha256:ctx",
        scope_version_id="scope-1",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        previous_effective_assessment_id=previous,
    )


def _context(**updates) -> GraphContextSnapshot:
    """context."""
    values = {
        "context_snapshot_id": "ctx-1",
        "input_hash": "sha256:ctx",
        "scope_version_id": "scope-1",
        "security_id": "000001.SZ",
        "decision_at": DECISION_AT,
        "quant_input_valid": True,
        "pit_valid": True,
        "news_target_complete": True,
        "provider_budget_available": True,
        "review_due": False,
        "material_quant_change": False,
        "material_valuation_change": False,
        "material_news_change": False,
        "assumption_change": False,
        "ambiguous_change": False,
    }
    values.update(updates)
    return GraphContextSnapshot(**values)
