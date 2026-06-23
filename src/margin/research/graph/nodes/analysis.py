"""Parallel analysis nodes and fan-in reducers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from margin.research.graph.state import AIDeltaGraphState
from margin.research.tools.definitions import ToolCapability
from margin.research.tools.factory import ScopedToolFactory, ScopedToolSession


class AnalysisRequest(BaseModel):
    """Frozen input supplied to one analysis handler."""

    node_name: str
    security_id: str
    decision_at: datetime
    evidence_package_ids: tuple[str, ...]
    package_summaries: dict[str, Any] = Field(default_factory=dict)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


AnalysisHandler = Callable[
    [AnalysisRequest, ScopedToolSession],
    dict[str, Any],
]


NODE_GRANTS: dict[str, set[ToolCapability]] = {
    "fundamental_analysis": {
        ToolCapability.FINANCIAL_READ,
        ToolCapability.QUANT_READ,
    },
    "valuation_analysis": {
        ToolCapability.DETERMINISTIC_VALUATION,
        ToolCapability.RESTRICTED_CALCULATION,
    },
    "risk_review": {
        ToolCapability.NEWS_READ,
        ToolCapability.FILING_READ,
    },
    "counter_argument": set(),
    "targeted_reanalysis": {
        ToolCapability.FINANCIAL_READ,
        ToolCapability.QUANT_READ,
        ToolCapability.NEWS_READ,
        ToolCapability.FILING_READ,
        ToolCapability.DETERMINISTIC_VALUATION,
        ToolCapability.RESTRICTED_CALCULATION,
    },
}


class AnalysisNode:
    """Execute one scoped analysis handler without retrieval capability."""

    def __init__(
        self,
        *,
        node_name: str,
        tool_factory: ScopedToolFactory,
        handler: AnalysisHandler,
    ) -> None:
        """Initialize the instance."""
        self.node_name = node_name
        self._tool_factory = tool_factory
        self._handler = handler

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        session = self._tool_factory.create_session(
            graph_run_id=state.graph_run_id,
            node_name=self.node_name,
            security_id=state.security_id,
            decision_at=state.decision_at,
            grants=NODE_GRANTS[self.node_name],
            max_calls=4,
            max_result_bytes=131_072,
        )
        request = AnalysisRequest(
            node_name=self.node_name,
            security_id=state.security_id,
            decision_at=state.decision_at,
            evidence_package_ids=state.evidence_package_ids,
            package_summaries=dict(
                state.node_outputs.get("evidence_packages", {})
            ),
            evidence_gaps=state.evidence_gaps,
        )
        try:
            output = self._handler(request, session)
        except Exception as exc:  # noqa: BLE001 - external text is not persisted
            return {
                "node_outputs": {
                    self.node_name: {
                        "success": False,
                        "error_type": type(exc).__name__,
                    }
                },
                "errors": (f"{self.node_name}:{type(exc).__name__}",),
                "tool_call_ids": session.call_ids,
                "graph_step_count": 1,
            }
        gaps = tuple(str(value) for value in output.get("evidence_gaps", ()))
        llm_call_ids = tuple(
            str(value) for value in output.get("llm_call_ids", ())
        )
        return {
            "node_outputs": {self.node_name: output},
            "evidence_gaps": gaps,
            "tool_call_ids": session.call_ids,
            "llm_call_ids": llm_call_ids,
            "llm_call_count": len(llm_call_ids),
            "graph_step_count": 1,
        }


class AnalysisJoinNode:
    """Validate that the four parallel analysis branches completed."""

    required_nodes = (
        "fundamental_analysis",
        "valuation_analysis",
        "risk_review",
        "counter_argument",
    )

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        completed = tuple(
            node_name
            for node_name in self.required_nodes
            if node_name in state.node_outputs
        )
        errors = (
            ()
            if len(completed) == len(self.required_nodes)
            else ("analysis_fan_in_incomplete",)
        )
        return {
            "node_outputs": {
                "analysis_join": {
                    "completed_nodes": completed,
                    "completed_count": len(completed),
                }
            },
            "errors": errors,
            "graph_step_count": 1,
        }


class EvidenceGapRouter:
    """Record the deterministic supplemental-retrieval routing decision."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Call the instance."""
        return {
            "node_outputs": {
                "evidence_gap_router": {
                    "has_specific_gaps": bool(state.evidence_gaps),
                    "retrieval_count": state.retrieval_count,
                }
            },
            "graph_step_count": 1,
        }


class TargetedReanalysisNode(AnalysisNode):
    """Reanalyze only the explicit gaps after the one supplemental retrieval."""

    def __init__(
        self,
        *,
        tool_factory: ScopedToolFactory,
        handlers: Mapping[str, AnalysisHandler],
    ) -> None:
        """Initialize the instance."""
        super().__init__(
            node_name="targeted_reanalysis",
            tool_factory=tool_factory,
            handler=handlers["targeted_reanalysis"],
        )
