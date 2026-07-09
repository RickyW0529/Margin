"""v0.2 scoped research-tool policy and factory tests.

This module verifies that the tool policy engine denies forbidden capabilities
and ungranted capabilities, that the scoped tool factory exposes only
node-granted tools, and that the tool executor enforces PIT safety, security
scope isolation, call budgets, result byte limits, and audits denials for
unknown tools and invalid inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.research.tools.executor import MemoryToolCallAuditRepository
from margin.research.tools.factory import ScopedToolFactory
from margin.research.tools.policy import ToolPolicyEngine

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


class EvidenceQuery(BaseModel):
    """Input model for the evidence retrieval tool.."""

    security_id: str
    decision_at: datetime
    query: str = ""


class ValuationInput(BaseModel):
    """Input model for the deterministic valuation tool.."""

    security_id: str
    decision_at: datetime
    earnings: float
    multiple: float


def test_policy_denies_realtime_websearch_inside_graph() -> None:
    """Verify the policy denies realtime websearch inside the graph.

    Returns:
        None: .
    """
    policy = ToolPolicyEngine()

    decision = policy.authorize(
        node_name="risk_review",
        capability=ToolCapability.REALTIME_WEBSEARCH,
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        node_grants={ToolCapability.REALTIME_WEBSEARCH},
    )

    assert decision.allowed is False
    assert decision.reason_code == "capability_forbidden"


def test_policy_denies_capability_not_granted_to_node() -> None:
    """Verify the policy denies a capability not granted to the node.

    Returns:
        None: .
    """
    decision = ToolPolicyEngine().authorize(
        node_name="risk_review",
        capability=ToolCapability.EVIDENCE_RETRIEVE,
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        node_grants={ToolCapability.NEWS_READ},
    )

    assert decision.allowed is False
    assert decision.reason_code == "capability_not_granted"


def test_scoped_factory_exposes_only_node_granted_tools() -> None:
    """Verify the scoped factory exposes only tools granted to the node.

    Returns:
        None: .
    """
    registry = _registry()
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-1",
        node_name="valuation_analysis",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.DETERMINISTIC_VALUATION},
        max_calls=2,
        max_result_bytes=4_096,
    )

    manifest = session.manifest()

    assert [tool.name for tool in manifest.tools] == ["deterministic_valuation"]
    assert "websearch" not in {tool.name for tool in manifest.tools}


def test_tool_executor_enforces_pit_and_audits_denial() -> None:
    """Verify the tool executor enforces PIT safety and audits denials.

    Returns:
        None: .
    """
    audit = MemoryToolCallAuditRepository()
    session = ScopedToolFactory(
        tool_registry=_registry(),
        policy=ToolPolicyEngine(),
        audit_repository=audit,
    ).create_session(
        graph_run_id="graph-1",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    result = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": "2026-06-23T00:00:00Z",
            "query": "风险事件",
        },
    )

    assert result.success is False
    assert result.error_code == "pit_violation"
    [record] = audit.records
    assert record.allowed is False
    assert record.error_code == "pit_violation"
    assert record.request_hash.startswith("sha256:")


def test_tool_executor_denies_cross_security_and_call_budget() -> None:
    """Verify the tool executor denies cross-security access and enforces call budgets.

    Returns:
        None: .
    """
    session = ScopedToolFactory(
        tool_registry=_registry(),
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-1",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
        max_calls=1,
    )

    wrong_security = session.call(
        "evidence_retrieve",
        {
            "security_id": "600000.SH",
            "decision_at": DECISION_AT,
            "query": "公告",
        },
    )
    first = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT,
            "query": "公告",
        },
    )
    over_budget = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT,
            "query": "财报",
        },
    )

    assert wrong_security.error_code == "security_scope_violation"
    assert first.success is True
    assert over_budget.error_code == "call_budget_exceeded"


def test_tool_executor_enforces_result_byte_limit() -> None:
    """Verify the tool executor enforces the result byte limit.

    Returns:
        None: .
    """
    session = ScopedToolFactory(
        tool_registry=_registry(large_result=True),
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-1",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
        max_result_bytes=32,
    )

    result = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT,
            "query": "公告",
        },
    )

    assert result.success is False
    assert result.error_code == "result_too_large"
    assert result.data is None


def test_unknown_tool_and_invalid_decision_are_denied_and_audited() -> None:
    """Verify unknown tools and invalid decision-at values are denied and audited.

    Returns:
        None: .
    """
    audit = MemoryToolCallAuditRepository()
    session = ScopedToolFactory(
        tool_registry=_registry(),
        policy=ToolPolicyEngine(),
        audit_repository=audit,
    ).create_session(
        graph_run_id="graph-1",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    unknown = session.call("missing_tool", {"security_id": "000001.SZ"})
    invalid_time = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": "not-a-date",
            "query": "公告",
        },
    )

    assert unknown.call_id
    assert unknown.error_code == "tool_not_registered"
    assert invalid_time.error_code == "invalid_decision_at"
    assert [record.error_code for record in audit.records] == [
        "tool_not_registered",
        "invalid_decision_at",
    ]
    assert all(record.allowed is False for record in audit.records)


def _registry(*, large_result: bool = False) -> ToolDefinitionRegistry:
    """Build a tool definition registry with evidence, valuation, and websearch tools.

    Args:
        large_result: bool: .

    Returns:
        ToolDefinitionRegistry: .
    """
    registry = ToolDefinitionRegistry()
    registry.register(
        ToolDefinition(
            name="evidence_retrieve",
            capability=ToolCapability.EVIDENCE_RETRIEVE,
            version="evidence-retrieve-v0.2.0",
            description="Retrieve frozen PIT-safe evidence.",
            input_model=EvidenceQuery,
            handler=lambda payload: (
                {"content": "x" * 1_000}
                if large_result
                else {"package_id": "pkg-1", "query": payload["query"]}
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="deterministic_valuation",
            capability=ToolCapability.DETERMINISTIC_VALUATION,
            version="deterministic-valuation-v0.2.0",
            description="Run deterministic valuation arithmetic.",
            input_model=ValuationInput,
            handler=lambda payload: {"value": payload["earnings"] * payload["multiple"]},
        )
    )
    registry.register(
        ToolDefinition(
            name="websearch",
            capability=ToolCapability.REALTIME_WEBSEARCH,
            version="websearch-v0.2.0",
            description="Forbidden realtime web search.",
            input_model=EvidenceQuery,
            handler=lambda payload: payload,
        )
    )
    return registry
