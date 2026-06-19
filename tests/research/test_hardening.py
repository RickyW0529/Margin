"""Regression tests for module 06 safety and audit boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.evidence.models import Evidence, make_claim
from margin.news.models import SourceLevel
from margin.research.agents import AgentContext, CitationValidatorAgent
from margin.research.llm import DeterministicLLMProvider, StructuredOutputGuardrail
from margin.research.models import ResearchSignal, SignalType, WorkflowState
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.tools import (
    FactorTool,
    MarketDataTool,
    PortfolioTool,
    ToolRegistry,
    ToolResult,
)
from margin.research.workflow import ResearchWorkflow
from margin.vector.models import DocType, make_chunk


class _EvidenceRetrievalTool:
    name = "retrieval"
    permission = "read"

    def run(self, params: dict[str, Any]) -> ToolResult:
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
            tool_name=self.name,
            success=True,
            data=[{"chunk": chunk.model_dump(), "score": 0.9}],
            params=params,
        )


def _registry_with_evidence() -> ToolRegistry:
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
            lambda params: {"violations": [], "current_weight": 0.0}
        )
    )
    registry.register(_EvidenceRetrievalTool())
    return registry


def test_write_tool_requires_explicit_confirmation() -> None:
    registry = _registry_with_evidence()

    result = registry.call("alert", {"message": "review"})

    assert result.success is False
    assert result.error == "confirmation required"


def test_unconfigured_market_tool_fails_closed() -> None:
    registry = ToolRegistry()
    registry.register_defaults()

    result = registry.call("market_data", {"symbol": "000001.SZ"})

    assert result.success is False
    assert "not configured" in (result.error or "")


def test_every_tool_call_creates_audit_record() -> None:
    registry = ToolRegistry()
    registry.register_defaults()

    result = registry.call("python", {"expression": "1 + 1"}, trace_id="trace-1")

    assert result.success is True
    assert result.call_id
    assert registry.audit_records[-1].call_id == result.call_id
    assert registry.audit_records[-1].trace_id == "trace-1"


def test_tool_audit_redacts_result_payload() -> None:
    registry = ToolRegistry()
    registry.register(
        MarketDataTool(
            lambda params: {
                "symbol": params["symbol"],
                "api_key": "must-not-leak",
            }
        )
    )

    result = registry.call("market_data", {"symbol": "000001.SZ"})
    audited_data = registry.audit_records[-1].data

    assert result.success is True
    assert audited_data == {"symbol": "000001.SZ", "api_key": "***"}
    audited_data["symbol"] = "changed"
    assert registry.audit_records[-1].data["symbol"] == "000001.SZ"


def test_guardrail_rejects_wrong_scalar_type() -> None:
    guardrail = StructuredOutputGuardrail(
        {
            "type": "object",
            "properties": {"risk_score": {"type": "number"}},
            "required": ["risk_score"],
        }
    )

    ok, message = guardrail.validate({"risk_score": "high"})

    assert ok is False
    assert "risk_score" in message


def test_citation_validator_rejects_unknown_evidence_reference() -> None:
    registry = ToolRegistry()
    registry.register_defaults()
    context = AgentContext(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        prior_outputs={"signal_composer": {"evidence_refs": ["missing-evidence"]}},
    )

    output = CitationValidatorAgent().run(context)

    assert output.data["valid"] is False
    assert "not found" in output.data["reason"].lower()


def test_citation_validator_rejects_evidence_not_referenced_by_claim() -> None:
    registry = _registry_with_evidence()
    target = Evidence.from_chunk(
        make_chunk(
            document_id="doc-target",
            content="目标证据",
            symbol="000001.SZ",
            source_level=SourceLevel.L1,
            doc_type=DocType.FILING,
            source_url="https://example.com/target.pdf",
            page=1,
            published_at=datetime(2026, 6, 17, tzinfo=UTC),
            available_at=datetime(2026, 6, 17, tzinfo=UTC),
        )
    )
    claimed = Evidence.from_chunk(
        make_chunk(
            document_id="doc-claimed",
            content="已引用证据",
            symbol="000001.SZ",
            source_level=SourceLevel.L1,
            doc_type=DocType.FILING,
            source_url="https://example.com/claimed.pdf",
            page=1,
            published_at=datetime(2026, 6, 17, tzinfo=UTC),
            available_at=datetime(2026, 6, 17, tzinfo=UTC),
        )
    )
    context = AgentContext(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
        prior_outputs={
            "signal_composer": {"evidence_refs": [target.evidence_id]}
        },
        evidences={
            target.evidence_id: target,
            claimed.evidence_id: claimed,
        },
        claims=[
            make_claim(
                "仅引用另一条证据",
                evidence_ids=[claimed.evidence_id],
                effective_at=datetime(2026, 6, 18, tzinfo=UTC),
            )
        ],
    )

    output = CitationValidatorAgent().run(context)

    assert output.data["valid"] is False
    assert "not referenced by a claim" in output.data["reason"].lower()


def test_all_llm_failures_cannot_publish_candidate() -> None:
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=_registry_with_evidence(),
        llm_provider=DeterministicLLMProvider(fail=True),
    )

    result = workflow.run()

    assert result.state == WorkflowState.ABSTAINED
    assert all(signal.signal_type != SignalType.RESEARCH_CANDIDATE for signal in result.signals)


def test_abstained_workflow_has_snapshot() -> None:
    registry = _registry_with_evidence()
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
    )

    result = workflow.run()

    assert result.state == WorkflowState.ABSTAINED
    assert result.snapshot is not None
    assert result.snapshot_persisted is True
    assert result.snapshot["workflow_state"] == WorkflowState.ABSTAINED
    assert result.snapshot["agent_outputs_json"] != "{}"
    assert result.snapshot["tool_calls_json"] != "[]"


def test_data_failure_aborts_with_snapshot() -> None:
    registry = ToolRegistry()
    registry.register_defaults()
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=registry,
    )

    result = workflow.run()

    assert result.state == WorkflowState.ABORTED
    assert result.snapshot is not None
    assert result.snapshot_persisted is True
    assert result.snapshot["workflow_state"] == WorkflowState.ABORTED


def test_snapshot_persistence_failure_aborts_without_persisted_id() -> None:
    class FailingRepository:
        def add_snapshot(self, snapshot: Any) -> None:
            del snapshot
            raise RuntimeError("database unavailable")

    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=_registry_with_evidence(),
        repository=FailingRepository(),
    )

    result = workflow.run()

    assert result.state == WorkflowState.ABORTED
    assert result.snapshot_persisted is False
    assert result.signals == []
    assert "snapshot persistence failed" in (result.error or "")


def test_snapshot_nested_collections_are_immutable() -> None:
    signal = ResearchSignal(
        symbol="000001.SZ",
        signal_type=SignalType.WATCH,
        evidence_refs=["ev_1"],
    )
    snapshot = (
        ResearchSnapshotBuilder()
        .for_run("run-1")
        .with_state(WorkflowState.PUBLISHED)
        .with_symbols(["000001.SZ"])
        .with_signals([signal])
        .build()
    )

    assert isinstance(signal.evidence_refs, tuple)
    assert isinstance(snapshot.symbols, tuple)
    assert isinstance(snapshot.signals, tuple)


def test_workflow_traces_contain_input_and_output_hashes() -> None:
    workflow = ResearchWorkflow(
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
        tool_registry=_registry_with_evidence(),
        llm_provider=DeterministicLLMProvider(fail=True),
    )

    result = workflow.run()

    assert result.traces
    assert all(trace.input_hash for trace in result.traces)
    assert all(trace.output_hash for trace in result.traces)
