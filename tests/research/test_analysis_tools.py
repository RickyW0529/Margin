"""Analysis Mart scoped tool tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from margin.research.analysis_tools import register_analysis_mart_tools
from margin.research.graph.nodes.analysis import NODE_GRANTS
from margin.research.service import ResearchContextSnapshot, _default_tool_factory
from margin.research.tools.definitions import ToolCapability, ToolDefinitionRegistry
from margin.research.tools.factory import ScopedToolFactory
from margin.research.tools.policy import ToolPolicyEngine
from margin.valuation_discovery.analysis_mart import (
    AnalysisMartPublisher,
    MemoryAnalysisMartRepository,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)

DECISION_AT = datetime(2026, 6, 24, 8, 0, tzinfo=UTC)


def test_analysis_mart_tools_read_snapshot_metrics_and_findings() -> None:
    """Scoped tools expose fourth-layer analysis rows to AI nodes."""
    repository = _repository()
    registry = ToolDefinitionRegistry()
    register_analysis_mart_tools(registry, repository=repository)
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-analysis-tools",
        node_name="fundamental_analysis",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.QUANT_READ},
    )

    manifest_names = {tool.name for tool in session.manifest().tools}
    assert {
        "analysis_snapshot_get",
        "analysis_metrics_list",
        "analysis_findings_list",
    } <= manifest_names

    snapshot = session.call(
        "analysis_snapshot_get",
        {
            "security_id": "000001.SZ",
            "scope_version_id": "scope-v1",
            "decision_at": DECISION_AT.isoformat(),
        },
    )
    assert snapshot.success is True
    assert snapshot.data["snapshot"]["summary"]["final_score"] == 88.4

    metrics = session.call(
        "analysis_metrics_list",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "analysis_snapshot_id": snapshot.data["snapshot"]["analysis_snapshot_id"],
        },
    )
    assert metrics.success is True
    assert "raw_pe_ttm" in {metric["metric_code"] for metric in metrics.data["metrics"]}

    findings = session.call(
        "analysis_findings_list",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "analysis_snapshot_id": snapshot.data["snapshot"]["analysis_snapshot_id"],
        },
    )
    assert findings.success is True
    assert findings.data["findings"][0]["finding_type"] == "quant_screening"


def test_analysis_mart_tools_deny_cross_security() -> None:
    """Existing scoped policy blocks tools from reading another security."""
    repository = _repository()
    registry = ToolDefinitionRegistry()
    register_analysis_mart_tools(registry, repository=repository)
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-analysis-tools",
        node_name="fundamental_analysis",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.QUANT_READ},
    )

    result = session.call(
        "analysis_snapshot_get",
        {
            "security_id": "600000.SH",
            "scope_version_id": "scope-v1",
            "decision_at": DECISION_AT.isoformat(),
        },
    )

    assert result.success is False
    assert result.error_code == "security_scope_violation"


def test_default_research_tool_factory_registers_analysis_tools() -> None:
    """Production default tool factory exposes Analysis Mart tools when provided."""
    repository = _repository()
    context = ResearchContextSnapshot(
        context_snapshot_id="context-analysis-tools",
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        decision_at=DECISION_AT,
        payload_hash="sha256:context",
        payload={"analysis_snapshot_id": "asnap"},
    )

    session = _default_tool_factory(
        context,
        analysis_mart_repository=repository,
    ).create_session(
        graph_run_id="graph-analysis-tools",
        node_name="fundamental_analysis",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.QUANT_READ},
    )

    assert "analysis_snapshot_get" in {tool.name for tool in session.manifest().tools}


def test_valuation_analysis_node_can_read_analysis_mart() -> None:
    """Valuation analysis needs QUANT_READ to inspect Analysis Mart metrics."""
    assert ToolCapability.QUANT_READ in NODE_GRANTS["valuation_analysis"]


def _repository() -> MemoryAnalysisMartRepository:
    repository = MemoryAnalysisMartRepository()
    publisher = AnalysisMartPublisher(repository)
    publisher.publish_quant_result(
        scope_version_id="scope-v1",
        decision_at=DECISION_AT,
        trading_date=date(2026, 6, 24),
        quant_result=QuantResult(
            result_id="quant-result-tools",
            quant_run_id="quant-run-tools",
            security_id="000001.SZ",
            final_score=88.4,
            value_score=91.0,
            screening_status=ScreeningStatus.PASS,
            data_status=DataStatus.OK,
            research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
            factor_details={
                "ai_quant_profile": {
                    "scores": {"manual_all_a_score": 88.4},
                    "raw_factors": {"pe_ttm": 8.2, "pb": 0.68},
                }
            },
            created_at=DECISION_AT,
        ),
        input_snapshot_id="quant-input-tools",
        strategy_version_id="strategy-tools",
        config_hash="sha256:config",
        input_hash="sha256:input",
        evidence_ids=("evidence-tools",),
    )
    return repository
