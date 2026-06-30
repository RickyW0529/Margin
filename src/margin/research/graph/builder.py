"""LangGraph topology for the controlled v0.2 AI delta review."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from margin.research.graph.nodes.analysis import (
    AnalysisHandler,
    AnalysisJoinNode,
    AnalysisNode,
    EvidenceGapRouter,
    TargetedReanalysisNode,
)
from margin.research.graph.nodes.decision import (
    AbstainNode,
    CarryForwardDecisionNode,
    CitationValidationHandler,
    CitationValidationNode,
    DecisionHandler,
    DeltaDecisionComposerNode,
    FinalizeNode,
    RepairDecisionNode,
    ReviewDeferredNode,
)
from margin.research.graph.nodes.evidence import (
    AdditionalEvidenceRetrievalNode,
    EvidencePlanNode,
    RetrieveEvidenceNode,
)
from margin.research.graph.state import (
    AIDeltaGraphState,
    ReviewMode,
    ReviewOutcome,
)
from margin.research.tools.factory import ScopedToolFactory


@dataclass(frozen=True)
class GraphDependencies:
    """Dependencies required by the graph topology."""

    tool_factory: ScopedToolFactory
    analysis_handlers: Mapping[str, AnalysisHandler]
    allow_supplemental_retrieval: bool = True
    decision_handler: DecisionHandler = lambda state: _default_decision(state)
    citation_validator: CitationValidationHandler = (
        lambda draft, state: _default_citation_validation(draft, state)
    )
    checkpointer: Any | None = None
    interrupt_after: tuple[str, ...] | None = None


def build_ai_delta_review_graph(dependencies: GraphDependencies) -> Any:
    """Build a real LangGraph with centralized retrieval and parallel analyses.

    Args:
        dependencies: Frozen dependencies including tool factory, handlers,
            and optional checkpointer.

    Returns:
        A compiled LangGraph ready for invocation.
    """
    graph = StateGraph(AIDeltaGraphState)
    graph.add_node("evidence_plan", EvidencePlanNode())
    graph.add_node(
        "retrieve_evidence",
        RetrieveEvidenceNode(dependencies.tool_factory),
    )
    analysis_names = (
        "fundamental_analysis",
        "valuation_analysis",
        "risk_review",
        "counter_argument",
    )
    for node_name in analysis_names:
        graph.add_node(
            node_name,
            AnalysisNode(
                node_name=node_name,
                tool_factory=dependencies.tool_factory,
                handler=dependencies.analysis_handlers[node_name],
            ),
        )
    graph.add_node("analysis_join", AnalysisJoinNode())
    graph.add_node("evidence_gap_router", EvidenceGapRouter())
    graph.add_node(
        "additional_evidence_retrieval",
        AdditionalEvidenceRetrievalNode(dependencies.tool_factory),
    )
    graph.add_node(
        "targeted_reanalysis",
        TargetedReanalysisNode(
            tool_factory=dependencies.tool_factory,
            handlers=dependencies.analysis_handlers,
        ),
    )
    graph.add_node(
        "delta_decision",
        DeltaDecisionComposerNode(dependencies.decision_handler),
    )
    graph.add_node(
        "citation_validation",
        CitationValidationNode(dependencies.citation_validator),
    )
    graph.add_node("repair_decision", RepairDecisionNode())
    graph.add_node("carry_forward", CarryForwardDecisionNode())
    graph.add_node("review_deferred", ReviewDeferredNode())
    graph.add_node("abstain", AbstainNode())
    graph.add_node("finalize", FinalizeNode())

    graph.add_conditional_edges(
        START,
        _route_start,
        {
            "review": "evidence_plan",
            "carry_forward": "carry_forward",
            "review_deferred": "review_deferred",
            "abstain": "abstain",
        },
    )
    graph.add_edge("evidence_plan", "retrieve_evidence")
    for node_name in analysis_names:
        graph.add_edge("retrieve_evidence", node_name)
    graph.add_edge(list(analysis_names), "analysis_join")
    graph.add_edge("analysis_join", "evidence_gap_router")
    graph.add_conditional_edges(
        "evidence_gap_router",
        lambda state: _route_gap(
            state,
            allow_supplemental=dependencies.allow_supplemental_retrieval,
        ),
        {
            "supplement": "additional_evidence_retrieval",
            "done": "delta_decision",
        },
    )
    graph.add_edge("additional_evidence_retrieval", "targeted_reanalysis")
    graph.add_edge("targeted_reanalysis", "delta_decision")
    graph.add_edge("delta_decision", "citation_validation")
    graph.add_conditional_edges(
        "citation_validation",
        _route_citation,
        {
            "valid": "finalize",
            "repair": "repair_decision",
            "abstain": "abstain",
        },
    )
    graph.add_conditional_edges(
        "repair_decision",
        _route_after_repair,
        {
            "revalidate": "citation_validation",
            "abstain": "abstain",
        },
    )
    graph.add_edge("carry_forward", "finalize")
    graph.add_edge("review_deferred", "finalize")
    graph.add_edge("abstain", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(
        checkpointer=dependencies.checkpointer,
        interrupt_after=list(dependencies.interrupt_after)
        if dependencies.interrupt_after
        else None,
    )


def _route_start(state: AIDeltaGraphState) -> str:
    """Route the initial state to review, carry-forward, deferred, or abstain."""
    if state.review_mode in {ReviewMode.FULL_REVIEW, ReviewMode.DELTA_REVIEW}:
        return "review"
    if state.review_mode == ReviewMode.CARRY_FORWARD_FAST_PATH:
        return "carry_forward"
    if state.review_mode == ReviewMode.REVIEW_DEFERRED:
        return "review_deferred"
    return "abstain"


def _route_gap(
    state: AIDeltaGraphState,
    *,
    allow_supplemental: bool,
) -> str:
    """Route after analysis join to supplemental retrieval or decision."""
    if (
        allow_supplemental
        and state.evidence_gaps
        and state.retrieval_count == 1
    ):
        return "supplement"
    return "done"


def _route_citation(state: AIDeltaGraphState) -> str:
    """Route after citation validation to finalize, repair, or abstain."""
    if state.citation_report.get("valid") is True:
        return "valid"
    if state.repair_count == 0:
        return "repair"
    return "abstain"


def _route_after_repair(state: AIDeltaGraphState) -> str:
    """Route after repair decision to revalidation or abstain."""
    if state.current_review_outcome == ReviewOutcome.ABSTAIN:
        return "abstain"
    return "revalidate"


def _default_decision(state: AIDeltaGraphState) -> dict[str, Any]:
    """Return a deterministic abstain decision when no handler is configured."""
    del state
    return {
        "outcome": ReviewOutcome.ABSTAIN.value,
        "confidence": 0.0,
        "evidence_ids": [],
        "changed_assumptions": [],
        "llm_call_ids": [],
    }


def _default_citation_validation(
    draft: dict[str, Any],
    state: AIDeltaGraphState,
) -> dict[str, Any]:
    """Return a default valid citation report when no validator is configured."""
    del draft, state
    return {
        "valid": True,
        "repairable": False,
        "invalid_evidence_ids": [],
    }
