"""Research workflow state machine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from margin.evidence.models import Claim, Evidence
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
    ValuationToolAgent,
    WebSearchAgent,
)
from margin.research.llm import LLMProvider, ModelRouter
from margin.research.models import (
    AgentTrace,
    ResearchSignal,
    ResearchSnapshot,
    SignalType,
    WorkflowState,
)
from margin.research.repository import (
    MemoryResearchRepository,
    ResearchRepository,
)
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.tools import ToolRegistry


@dataclass
class WorkflowResult:
    """Result of a workflow run."""

    run_id: str
    state: WorkflowState
    signals: list[ResearchSignal] = field(default_factory=list)
    prior_outputs: dict[str, Any] = field(default_factory=dict)
    traces: list[AgentTrace] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None
    snapshot_persisted: bool = False
    error: str | None = None


class ResearchWorkflow:
    """Nightly research workflow state machine."""

    def __init__(
        self,
        symbol: str,
        decision_at: datetime,
        tool_registry: ToolRegistry,
        llm_provider: LLMProvider | None = None,
        model_router: ModelRouter | None = None,
        strategy_config: dict[str, Any] | None = None,
        portfolio_id: str | None = None,
        claims: list[Claim] | None = None,
        evidences: dict[str, Evidence] | None = None,
        snapshot_resolver: Any | None = None,
        repository: ResearchRepository | None = None,
    ) -> None:
        self._run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._symbol = symbol
        self._decision_at = decision_at
        self._tools = tool_registry
        self._llm = llm_provider
        self._model_router = model_router
        self._strategy = strategy_config or {}
        self._portfolio_id = portfolio_id
        self._state = WorkflowState.INITIALIZED
        self._prior_outputs: dict[str, Any] = {}
        self._traces: list[AgentTrace] = []
        self._claims = list(claims or [])
        self._evidences = dict(evidences or {})
        self._snapshot_resolver = snapshot_resolver
        self._repository = (
            repository
            if repository is not None
            else MemoryResearchRepository()
        )

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def state(self) -> WorkflowState:
        return self._state

    def _make_context(self) -> AgentContext:
        return AgentContext(
            symbol=self._symbol,
            decision_at=self._decision_at,
            tool_registry=self._tools,
            llm_provider=self._llm,
            model_router=self._model_router,
            portfolio_id=self._portfolio_id,
            strategy_config=self._strategy,
            prior_outputs=self._prior_outputs,
            claims=self._claims,
            evidences=self._evidences,
            snapshot_resolver=self._snapshot_resolver,
            trace_id=f"trc_{uuid.uuid4().hex[:12]}",
        )

    def _run_agent(self, agent) -> Any:
        context = self._make_context()
        output = agent.run(context)
        self._prior_outputs[agent.node_name] = output.data
        trace = AgentTrace(
            trace_id=output.trace_id,
            agent_node=agent.node_name,
            model_version=output.model_version,
            input_hash=output.input_hash,
            output_hash=output.output_hash,
            latency_ms=output.latency_ms,
            error=output.error,
            tool_call_ids=output.tool_call_ids,
        )
        self._traces.append(trace)
        return output

    def run(self) -> WorkflowResult:
        try:
            return self._execute()
        except Exception as exc:
            return self._finish(
                WorkflowState.ABORTED,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _execute(self) -> WorkflowResult:
        self._state = WorkflowState.DATA_READY

        # Agent 1 & 2: universe + quant
        universe_output = self._run_agent(UniverseFilterAgent())
        if not universe_output.success:
            return self._finish(WorkflowState.ABORTED, error=universe_output.error)

        quant_output = self._run_agent(QuantResearchAgent())
        if not quant_output.success:
            return self._finish(WorkflowState.ABORTED, error=quant_output.error)

        self._state = WorkflowState.EVIDENCE_READY

        # Agent 3 & 4: web search + document collection
        self._run_agent(WebSearchAgent(self._llm))
        self._run_agent(DocumentCollectorAgent())

        # Agent 5 & 6: summary + evidence research
        self._run_agent(TextSummaryAgent(self._llm))
        evidence_output = self._run_agent(EvidenceResearchAgent())
        if not evidence_output.success or not evidence_output.data.get("retrieval_results"):
            return self._finish(
                WorkflowState.ABSTAINED,
                error=evidence_output.error or "no valid evidence",
            )

        self._state = WorkflowState.ANALYSIS_READY

        # Agent 7: valuation
        self._run_agent(ValuationToolAgent())

        self._state = WorkflowState.REVIEW_READY

        # Agent 8, 9, 10: risk, reflect, portfolio
        risk_output = self._run_agent(RiskReviewAgent(self._llm))
        reflect_output = self._run_agent(ReflectCounterArgumentAgent(self._llm))
        portfolio_output = self._run_agent(PortfolioConstraintAgent())
        if not risk_output.success or not reflect_output.success:
            errors = [
                output.error
                for output in (risk_output, reflect_output)
                if not output.success and output.error
            ]
            return self._finish(
                WorkflowState.ABSTAINED,
                error="; ".join(errors) or "required LLM review failed",
            )

        # Agent 11: signal composer
        signal_output = self._run_agent(ResearchSignalComposer(self._llm))
        signal_data = signal_output.data

        # Agent 12: citation validator
        validator_output = self._run_agent(CitationValidatorAgent())
        if not validator_output.data.get("valid"):
            signal_data = {
                "signal_type": "abstained",
                "confidence": 0.0,
                "statement": validator_output.data.get("reason", "citation validation failed"),
                "evidence_refs": [],
            }
        else:
            capped = validator_output.data.get("capped_confidence")
            if isinstance(capped, (int, float)):
                signal_data["confidence"] = min(
                    signal_data.get("confidence", 0.0),
                    capped,
                )

        signal = ResearchSignal(
            symbol=self._symbol,
            signal_type=signal_data.get("signal_type", "abstained"),
            confidence=signal_data.get("confidence", 0.0),
            statement=signal_data.get("statement", ""),
            evidence_refs=signal_data.get("evidence_refs", []),
            claim_ids=[claim.claim_id for claim in self._claims],
            risk_score=risk_output.data.get("risk_score") if risk_output.success else None,
            counter_arguments=(
                reflect_output.data.get("counter_arguments", [])
                if reflect_output.success
                else []
            ),
            portfolio_constraint_violations=(
                portfolio_output.data.get("violations", [])
                if portfolio_output.success
                else []
            ),
        )

        terminal_state = (
            WorkflowState.ABSTAINED
            if signal.signal_type == SignalType.ABSTAINED
            else WorkflowState.PUBLISHED
        )
        terminal_error = (
            signal.statement
            if terminal_state == WorkflowState.ABSTAINED
            else None
        )
        return self._finish(
            terminal_state,
            signals=[signal],
            error=terminal_error,
        )

    def _finish(
        self,
        state: WorkflowState,
        *,
        signals: list[ResearchSignal] | None = None,
        error: str | None = None,
    ) -> WorkflowResult:
        self._state = state
        signals = signals or []
        snapshot = self._build_snapshot(state, signals, error)
        persisted = False
        try:
            self._repository.add_snapshot(snapshot)
            persisted = True
        except Exception as exc:
            state = WorkflowState.ABORTED
            self._state = state
            error = (
                f"snapshot persistence failed: {type(exc).__name__}: {exc}"
            )
            signals = []
            snapshot = self._build_snapshot(state, signals, error)
        return WorkflowResult(
            self._run_id,
            state,
            signals=signals,
            prior_outputs=dict(self._prior_outputs),
            traces=list(self._traces),
            snapshot=snapshot.model_dump(mode="json"),
            snapshot_persisted=persisted,
            error=error,
        )

    def _build_snapshot(
        self,
        state: WorkflowState,
        signals: list[ResearchSignal],
        error: str | None,
    ) -> ResearchSnapshot:
        snapshot = (
            ResearchSnapshotBuilder()
            .for_run(self._run_id)
            .with_state(state)
            .with_decision_at(self._decision_at)
            .with_symbols([self._symbol])
            .with_strategy_version(self._strategy.get("version", ""))
            .with_prompt_version(self._strategy.get("prompt_version", ""))
            .with_tool_versions({name: "1.0.0" for name in self._tools.list_tools()})
            .with_model_versions(
                {"default": self._llm.descriptor.version if self._llm else "rule"}
            )
            .with_evidence_ids(sorted(self._evidences))
            .with_claim_ids([claim.claim_id for claim in self._claims])
            .with_signals(signals)
            .with_traces(list(self._traces))
            .with_tool_call_ids(
                [record.call_id for record in self._tools.audit_records]
            )
            .with_tool_calls(
                [record.model_dump(mode="json") for record in self._tools.audit_records]
            )
            .with_prior_outputs(self._prior_outputs)
            .with_error(error)
            .build()
        )
        return snapshot
