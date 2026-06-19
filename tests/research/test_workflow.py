"""Tests for research workflow state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.news.models import SourceLevel
from margin.research.llm import DeterministicLLMProvider
from margin.research.models import WorkflowState
from margin.research.tools import (
    FactorTool,
    MarketDataTool,
    PortfolioTool,
    ToolRegistry,
)
from margin.research.workflow import ResearchWorkflow
from margin.vector.models import DocType, make_chunk


class _FakeRetrievalTool:
    name = "retrieval"
    permission = "read"

    def run(self, params: dict) -> Any:
        from margin.research.tools import ToolResult

        chunk = make_chunk(
            document_id="doc-1",
            content="经营现金流改善",
            symbol="000001.SZ",
            source_level=SourceLevel.L1,
            doc_type=DocType.FILING,
            source_url="https://example.com/filing.pdf",
            page=1,
            published_at=datetime(2026, 6, 17, tzinfo=UTC),
            available_at=datetime(2026, 6, 17, tzinfo=UTC),
        )
        return ToolResult(
            tool_name="retrieval",
            success=True,
            data=[
                {
                    "chunk": chunk.model_dump(),
                    "score": 0.9,
                }
            ],
            params=params,
        )


def _make_workflow(symbol: str = "000001.SZ", response: dict | None = None) -> ResearchWorkflow:
    registry = _configured_registry()
    registry.register(_FakeRetrievalTool())
    default_response = {
        "queries": ["q"],
        "summaries": [],
        "risk_score": 0.3,
        "risk_factors": [],
        "counter_arguments": [],
        "unknowns": [],
    }
    return ResearchWorkflow(
        symbol=symbol,
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(response=response or default_response),
    )


def _configured_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_defaults()
    registry.register(
        MarketDataTool(lambda params: {"symbol": params["symbol"], "close": 10.0})
    )
    registry.register(
        FactorTool(lambda params: {symbol: 0.5 for symbol in params["symbols"]})
    )
    registry.register(
        PortfolioTool(lambda params: {"violations": [], "current_weight": 0.0})
    )
    return registry


def test_workflow_runs_to_published():
    workflow = _make_workflow()
    result = workflow.run()
    assert result.state == WorkflowState.PUBLISHED
    assert len(result.signals) == 1
    assert result.signals[0].symbol == "000001.SZ"


def test_workflow_abstains_when_no_evidence():
    # Use default registry without fake retrieval -> evidence_research fails
    registry = _configured_registry()
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(
            response={"queries": ["q"], "summaries": []}
        ),
    )
    result = workflow.run()
    assert result.state == WorkflowState.ABSTAINED
    assert len(result.traces) > 0


def test_workflow_records_traces():
    workflow = _make_workflow()
    result = workflow.run()
    assert len(result.traces) > 0
    assert result.traces[0].trace_id.startswith("trc_")


def test_workflow_snapshot_contains_state():
    workflow = _make_workflow()
    result = workflow.run()
    assert result.snapshot is not None
    assert result.snapshot["workflow_state"] == "published"
    assert result.snapshot["input_hash"] != ""
    assert result.snapshot["output_hash"] != ""
