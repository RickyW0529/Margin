"""Tests for research agents."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.evidence.models import Evidence, make_claim
from margin.news.models import SourceLevel
from margin.research.agents import (
    AgentContext,
    CitationValidatorAgent,
    DocumentCollectorAgent,
    EvidenceResearchAgent,
    PortfolioConstraintAgent,
    QuantResearchAgent,
    ReflectCounterArgumentAgent,
    ResearchSignalComposer,
    RiskReviewAgent,
    TextSummaryAgent,
    UniverseFilterAgent,
    WebSearchAgent,
)
from margin.research.llm import DeterministicLLMProvider
from margin.research.tools import (
    DocumentCollectorTool,
    FactorTool,
    MarketDataTool,
    PortfolioTool,
    ToolRegistry,
)


def _make_context(
    symbol: str = "000001.SZ",
    prior_outputs: dict | None = None,
    strategy_config: dict | None = None,
    llm: DeterministicLLMProvider | None = None,
) -> AgentContext:
    registry = ToolRegistry()
    registry.register_defaults()
    registry.register(
        MarketDataTool(lambda params: {"symbol": params["symbol"], "close": 10.0})
    )
    registry.register(
        FactorTool(lambda params: {symbol: 0.5 for symbol in params["symbols"]})
    )
    registry.register(
        PortfolioTool(
            lambda params: {
                "violations": (
                    [
                        f"{params['symbol']} weight {params['current_weight']} "
                        f"exceeds {params['max_weight']}"
                    ]
                    if params["current_weight"] > params["max_weight"]
                    else []
                ),
                "current_weight": params["current_weight"],
            }
        )
    )
    registry.register(
        DocumentCollectorTool(
            lambda params: {
                "url": params["source"]["url"],
                "title": params["source"].get("title", ""),
                "content_hash": "sha256:test",
                "snapshot_id": "snap-1",
                "snapshot_hash": "sha256:snapshot",
            }
        )
    )
    return AgentContext(
        symbol=symbol,
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        llm_provider=llm,
        prior_outputs=prior_outputs or {},
        strategy_config=strategy_config or {},
    )


def test_universe_filter_agent_returns_symbols():
    agent = UniverseFilterAgent()
    context = _make_context(strategy_config={"universe": ["000001.SZ", "000002.SZ"]})
    output = agent.run(context)
    assert output.success is True
    assert "000001.SZ" in output.data["filtered"]


def test_quant_research_agent_ranks_symbols():
    agent = QuantResearchAgent()
    context = _make_context(
        strategy_config={"universe": ["000001.SZ", "000002.SZ"]},
        prior_outputs={"universe_filter": {"filtered": ["000001.SZ", "000002.SZ"]}},
    )
    output = agent.run(context)
    assert output.success is True
    assert "scores" in output.data
    assert context.symbol in output.data["ranked"]


def test_websearch_agent_uses_llm_for_queries():
    llm = DeterministicLLMProvider(response={"queries": ["平安银行 公告"]})
    agent = WebSearchAgent(llm)
    context = _make_context(llm=llm)
    output = agent.run(context)
    assert output.success is True
    assert "平安银行 公告" in output.data["queries"]


def test_document_collector_hashes_sources():
    agent = DocumentCollectorAgent()
    context = _make_context(
        prior_outputs={
            "websearch": {
                "results": [
                    {"url": "https://example.com/1", "title": "News"},
                ]
            }
        }
    )
    output = agent.run(context)
    assert output.success is True
    assert output.data["count"] == 1
    assert output.data["collected"][0]["content_hash"] != ""


def test_text_summary_agent_falls_back_when_no_documents():
    agent = TextSummaryAgent(DeterministicLLMProvider(response={"summaries": []}))
    context = _make_context()
    output = agent.run(context)
    assert output.success is True
    assert output.data["summaries"] == []


def test_evidence_research_agent_requires_retrieval_pipeline():
    agent = EvidenceResearchAgent()
    context = _make_context()
    output = agent.run(context)
    assert output.success is False
    assert "pipeline" in output.error.lower()


def test_portfolio_constraint_agent_detects_violation():
    agent = PortfolioConstraintAgent()
    context = _make_context(strategy_config={"max_position_weight": 0.05, "current_weight": 0.1})
    output = agent.run(context)
    assert output.success is True
    assert output.data["passed"] is False
    assert len(output.data["violations"]) == 1


def test_risk_review_agent_outputs_score_and_factors():
    llm = DeterministicLLMProvider(response={"risk_score": 0.3, "risk_factors": ["low debt"]})
    agent = RiskReviewAgent(llm)
    context = _make_context(llm=llm)
    output = agent.run(context)
    assert output.success is True
    assert output.data["risk_score"] == 0.3


def test_reflect_counter_argument_agent_outputs_lists():
    llm = DeterministicLLMProvider(response={"counter_arguments": ["c1"], "unknowns": ["u1"]})
    agent = ReflectCounterArgumentAgent(llm)
    context = _make_context(llm=llm)
    output = agent.run(context)
    assert output.success is True
    assert "c1" in output.data["counter_arguments"]


def test_signal_composer_abstains_on_portfolio_violation():
    agent = ResearchSignalComposer()
    context = _make_context(
        prior_outputs={
            "portfolio_constraint": {"passed": False, "violations": ["overweight"]},
            "evidence_research": {"retrieval_results": []},
        }
    )
    output = agent.run(context)
    assert output.success is True
    assert output.data["signal_type"] == "abstained"


def test_signal_composer_abstains_when_market_data_is_degraded():
    agent = ResearchSignalComposer()
    context = _make_context(
        prior_outputs={
            "universe_filter": {
                "filtered": ["000001.SZ"],
                "degraded": ["000001.SZ"],
            },
            "portfolio_constraint": {"passed": True, "violations": []},
            "evidence_research": {"evidence_ids": ["ev_1"]},
        }
    )

    output = agent.run(context)

    assert output.success is True
    assert output.data["signal_type"] == "abstained"
    assert "market data" in output.data["statement"].lower()


def test_citation_validator_fails_without_evidence_refs():
    agent = CitationValidatorAgent()
    context = _make_context(
        prior_outputs={"signal_composer": {"evidence_refs": []}}
    )
    output = agent.run(context)
    assert output.data["valid"] is False


def test_citation_validator_passes_with_refs():
    agent = CitationValidatorAgent()
    evidence = Evidence(
        evidence_id="ev_1",
        chunk_id="chunk_1",
        document_id="doc_1",
        source_type="filing_pdf",
        source_url="https://example.com/filing.pdf",
        source_level=SourceLevel.L1,
        content_hash="sha256:test",
        content="经营现金流改善",
        published_at=datetime(2026, 6, 17, tzinfo=UTC),
        available_at=datetime(2026, 6, 17, tzinfo=UTC),
        retrieved_at=datetime(2026, 6, 17, tzinfo=UTC),
        page=1,
    )
    claim = make_claim(
        "经营现金流改善",
        evidence_ids=["ev_1"],
        confidence=0.7,
        effective_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    context = _make_context(
        prior_outputs={"signal_composer": {"evidence_refs": ["ev_1"]}}
    )
    context.evidences["ev_1"] = evidence
    context.claims.append(claim)
    output = agent.run(context)
    assert output.data["valid"] is True


def test_citation_validator_rejects_lookahead_evidence():
    agent = CitationValidatorAgent()
    evidence = Evidence(
        evidence_id="ev_future",
        chunk_id="chunk_future",
        document_id="doc_future",
        source_type="filing_pdf",
        source_url="https://example.com/future.pdf",
        source_level=SourceLevel.L1,
        content_hash="sha256:future",
        content="未来公告",
        published_at=datetime(2026, 6, 19, tzinfo=UTC),
        available_at=datetime(2026, 6, 19, tzinfo=UTC),
        retrieved_at=datetime(2026, 6, 19, tzinfo=UTC),
        page=1,
    )
    claim = make_claim(
        "未来公告",
        evidence_ids=["ev_future"],
        confidence=0.7,
        effective_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    context = _make_context(
        prior_outputs={"signal_composer": {"evidence_refs": ["ev_future"]}}
    )
    context.evidences["ev_future"] = evidence
    context.claims.append(claim)

    output = agent.run(context)

    assert output.data["valid"] is False
    assert "lookahead" in output.data["reason"].lower()
