"""Analysis Mart scoped tool tests.

This module verifies that the Analysis Mart scoped read tools are correctly
registered, enforce per-security isolation, and are wired into the default
research tool factory so that AI research nodes can inspect fourth-layer
analysis rows.
"""

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
    QuantFeatureRow,
    QuantFeatureSnapshot,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)

DECISION_AT = datetime(2026, 6, 24, 8, 0, tzinfo=UTC)


def test_analysis_mart_tools_read_snapshot_metrics_and_findings() -> None:
    """Verify scoped tools expose fourth-layer analysis rows to AI nodes.

    Registers Analysis Mart tools against an in-memory repository, creates a
    scoped tool session with ``QUANT_READ`` grants, and asserts that the
    snapshot, metrics, findings, quant feature snapshot, and quant feature
    rows tools all return the expected seeded data.
    """
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
        "quant_feature_snapshot_get",
        "quant_feature_rows_list",
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

    feature_snapshot = session.call(
        "quant_feature_snapshot_get",
        {
            "scope_version_id": "scope-v1",
            "decision_at": DECISION_AT.isoformat(),
        },
    )
    assert feature_snapshot.success is True
    feature_snapshot_id = feature_snapshot.data["feature_snapshot"][
        "feature_snapshot_id"
    ]
    feature_rows = session.call(
        "quant_feature_rows_list",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "feature_snapshot_id": feature_snapshot_id,
        },
    )
    assert feature_rows.success is True
    assert feature_rows.data["feature_rows"][0]["features"]["pe_ttm"] == 8.2


def test_analysis_mart_tools_deny_cross_security() -> None:
    """Verify the scoped policy blocks tools from reading another security.

    Creates a session scoped to ``000001.SZ`` and asserts that calls targeting
    ``600000.SH`` are rejected with a ``security_scope_violation`` error code
    for both the analysis snapshot and quant feature rows tools.
    """
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

    feature_result = session.call(
        "quant_feature_rows_list",
        {
            "security_id": "600000.SH",
            "decision_at": DECISION_AT.isoformat(),
            "feature_snapshot_id": "qfsnap-tools",
        },
    )

    assert feature_result.success is False
    assert feature_result.error_code == "security_scope_violation"


def test_default_research_tool_factory_registers_analysis_tools() -> None:
    """Verify the production default tool factory exposes Analysis Mart tools.

    Builds a ``ResearchContextSnapshot`` and invokes the default tool factory
    with an Analysis Mart repository, then asserts that the resulting session
    manifest includes the ``analysis_snapshot_get`` and
    ``quant_feature_rows_list`` tools.
    """
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

    manifest_names = {tool.name for tool in session.manifest().tools}
    assert "analysis_snapshot_get" in manifest_names
    assert "quant_feature_rows_list" in manifest_names


def test_valuation_analysis_node_can_read_analysis_mart() -> None:
    """Verify the valuation analysis node holds the ``QUANT_READ`` grant.

    Asserts that ``QUANT_READ`` is present in the node grants for
    ``valuation_analysis``, ensuring it can inspect Analysis Mart metrics.
    """
    assert ToolCapability.QUANT_READ in NODE_GRANTS["valuation_analysis"]


def _repository() -> MemoryAnalysisMartRepository:
    """Build an in-memory Analysis Mart repository seeded with test data."""
    repository = MemoryAnalysisMartRepository()
    repository.upsert_feature_snapshot(
        QuantFeatureSnapshot(
            feature_snapshot_id="qfsnap-tools",
            scope_version_id="scope-v1",
            universe_snapshot_id="universe-tools",
            decision_at=DECISION_AT,
            known_at=DECISION_AT,
            trading_date=date(2026, 6, 24),
            feature_set_version_id="qfs-tools",
            feature_schema_version="quant-feature-mart-v0.3.0",
            source_layer="third_layer",
            input_hash="sha256:features",
            row_count=1,
            feature_columns=("pe_ttm", "pb", "roe_ttm"),
            lineage_summary={"quant_input_snapshot_id": "quant-input-tools"},
            quality_flags=("pit_valid",),
            created_at=DECISION_AT,
        ),
        (
            QuantFeatureRow(
                row_id="qfrow-tools-000001",
                feature_snapshot_id="qfsnap-tools",
                security_id="000001.SZ",
                symbol="000001.SZ",
                name="平安银行",
                industry_id="bank",
                features={"pe_ttm": 8.2, "pb": 0.68, "roe_ttm": 0.15},
                source_refs=(
                    {
                        "source_type": "canonical_fact",
                        "source_id": "fact-pe-tools",
                    },
                ),
                quality_flags=("pit_valid",),
                created_at=DECISION_AT,
            ),
        ),
    )
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
