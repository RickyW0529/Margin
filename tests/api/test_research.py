"""Tests for research API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.research.llm import DeterministicLLMProvider
from margin.research.service import ResearchService
from margin.research.tools import FactorTool, MarketDataTool, PortfolioTool, ToolRegistry


def _make_service() -> ResearchService:
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
    return ResearchService(
        tool_registry=registry,
        llm_provider=DeterministicLLMProvider(
            response={
                "queries": ["q"],
                "summaries": [],
                "risk_score": 0.3,
                "risk_factors": [],
                "counter_arguments": [],
                "unknowns": [],
            }
        ),
    )


def test_research_run_endpoint():
    service = _make_service()
    app = create_app(research_service=service)
    client = TestClient(app)
    response = client.post("/research/run", json={"symbol": "000001.SZ"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "abstained"  # no retrieval pipeline in test
    assert body["snapshot_id"]


def test_research_tools_endpoint():
    service = _make_service()
    app = create_app(research_service=service)
    client = TestClient(app)
    response = client.get("/research/tools")
    assert response.status_code == 200
    assert {"name": "python", "permission": "read"} in response.json()


def test_research_run_rejects_blank_symbol():
    app = create_app(research_service=_make_service())
    response = TestClient(app).post("/research/run", json={"symbol": "   "})

    assert response.status_code == 422
