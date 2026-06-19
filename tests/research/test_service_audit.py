"""Tests for research-snapshot audit integration."""

from __future__ import annotations

from margin.core.audit_repository import MemoryAuditRepository
from margin.research.llm import DeterministicLLMProvider
from margin.research.service import ResearchService
from margin.research.tools import FactorTool, MarketDataTool, PortfolioTool, ToolRegistry


def test_research_service_records_terminal_snapshot_in_audit_repository():
    registry = ToolRegistry()
    registry.register_defaults()
    registry.register(
        MarketDataTool(lambda params: {"symbol": params["symbol"], "close": 10.0})
    )
    registry.register(
        FactorTool(lambda params: {symbol: 0.5 for symbol in params["symbols"]})
    )
    registry.register(PortfolioTool(lambda params: {"violations": []}))
    audit_repository = MemoryAuditRepository()
    service = ResearchService(
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(
            response={"queries": ["q"], "summaries": []}
        ),
        audit_repository=audit_repository,
    )

    result = service.run("000001.SZ")

    records = audit_repository.list_records("research_snapshot")
    assert result.snapshot is not None
    assert len(records) == 1
    assert records[0].object_id == result.snapshot["snapshot_id"]
    assert records[0].input_hash == result.snapshot["input_hash"]
    assert records[0].output_hash == result.snapshot["output_hash"]
