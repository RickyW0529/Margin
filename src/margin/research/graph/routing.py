"""Stable route labels for the v0.2 graph builder."""

from __future__ import annotations

from margin.research.graph.state import AIDeltaGraphState, ReviewMode


def route_after_precheck(state: AIDeltaGraphState) -> str:
    """Route terminal precheck modes or continue to change-set construction."""
    if state.review_mode == ReviewMode.ABSTAIN:
        return "abstain"
    if state.review_mode == ReviewMode.REVIEW_DEFERRED:
        return "review_deferred"
    return "change_set_builder"


def route_after_change_set(state: AIDeltaGraphState) -> str:
    """Route deterministic review modes."""
    routes = {
        ReviewMode.FULL_REVIEW: "evidence_plan",
        ReviewMode.DELTA_REVIEW: "evidence_plan",
        ReviewMode.CARRY_FORWARD_FAST_PATH: "carry_forward",
        ReviewMode.REVIEW_DEFERRED: "review_deferred",
        ReviewMode.ABSTAIN: "abstain",
        None: "change_impact_classifier",
    }
    return routes[state.review_mode]
