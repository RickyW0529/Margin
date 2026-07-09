"""v0.2 LangGraph execution tests for retrieval discipline and fan-in.

This module verifies that the AI delta review graph enforces retrieval
discipline (analysis nodes cannot call retrieval tools), correctly fans in
parallel analysis outputs with gap deduplication, limits supplemental
retrieval to a single round, structures branch failures without losing
parallel outputs, and routes carry-forward, deferred, and citation-repair
outcomes deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from margin.research.graph.builder import (
    GraphDependencies,
    build_ai_delta_review_graph,
)
from margin.research.graph.nodes.analysis import AnalysisRequest
from margin.research.graph.state import (
    ReviewMode,
    ReviewOutcome,
    create_initial_state,
)
from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.research.tools.executor import MemoryToolCallAuditRepository
from margin.research.tools.factory import ScopedToolFactory, ScopedToolSession
from margin.research.tools.policy import ToolPolicyEngine

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


class RetrievalInput(BaseModel):
    """Input model for the evidence retrieval tool.."""

    security_id: str
    decision_at: datetime
    questions: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()
    supplemental: bool = False


class ValuationInput(BaseModel):
    """Input model for the deterministic valuation tool.."""

    security_id: str
    decision_at: datetime
    earnings: float
    multiple: float


def test_analysis_nodes_do_not_receive_or_call_retrieval_tools() -> None:
    """Verify analysis nodes never receive or call retrieval tools.

    Returns:
        None: .
    """
    fixture = GraphFixture()
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    retrieve_calls = [
        record
        for record in fixture.audit.records
        if record.capability == ToolCapability.EVIDENCE_RETRIEVE.value
    ]
    assert len(retrieve_calls) == 1
    assert {record.node_name for record in retrieve_calls} == {"retrieve_evidence"}
    assert fixture.analysis_tool_names
    assert all(
        "evidence_retrieve" not in tool_names for tool_names in fixture.analysis_tool_names.values()
    )
    assert result["retrieval_count"] == 1


def test_analysis_fan_in_preserves_all_outputs_and_deduplicates_gaps() -> None:
    """Verify analysis fan-in preserves all outputs and deduplicates gaps.

    Returns:
        None: .
    """
    fixture = GraphFixture(shared_gap=True, enable_supplemental=False)
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    assert {
        "fundamental_analysis",
        "valuation_analysis",
        "risk_review",
        "counter_argument",
    } <= set(result["node_outputs"])
    assert result["evidence_gaps"] == ("cash_flow_detail",)
    assert result["node_outputs"]["analysis_join"]["completed_count"] == 4


def test_evidence_gap_allows_only_one_supplemental_retrieval() -> None:
    """Verify an evidence gap triggers at most one supplemental retrieval.

    Returns:
        None: .
    """
    fixture = GraphFixture(shared_gap=True, enable_supplemental=True)
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    retrieve_calls = [
        record
        for record in fixture.audit.records
        if record.capability == ToolCapability.EVIDENCE_RETRIEVE.value
    ]
    assert result["retrieval_count"] == 2
    assert len(retrieve_calls) == 2
    assert {record.node_name for record in retrieve_calls} == {
        "retrieve_evidence",
        "additional_evidence_retrieval",
    }
    assert result["evidence_package_ids"] == ("pkg-initial", "pkg-supplemental")
    assert result["node_outputs"]["targeted_reanalysis"]["completed"] is True
    assert result["repair_count"] == 0


def test_analysis_failure_is_structured_without_losing_parallel_outputs() -> None:
    """Verify a failing analysis branch is structured without losing parallel outputs.
    Returns:.

    Returns:
        None: .
    """
    fixture = GraphFixture(failing_node="risk_review")
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    assert "risk_review:RuntimeError" in result["errors"]
    assert result["node_outputs"]["risk_review"]["success"] is False
    assert result["node_outputs"]["fundamental_analysis"]["completed"] is True
    assert result["node_outputs"]["valuation_analysis"]["completed"] is True
    assert result["node_outputs"]["counter_argument"]["completed"] is True
    assert result["node_outputs"]["analysis_join"]["completed_count"] == 4


def test_carry_forward_verified_keeps_effective_assessment_and_zero_llm() -> None:
    """Verify carry-forward fast path keeps the prior assessment with zero LLM calls.

    Returns:
        None: .
    """
    fixture = GraphFixture()
    graph = build_ai_delta_review_graph(fixture.dependencies())
    state = fixture.full_review_state().with_updates(
        review_mode=ReviewMode.CARRY_FORWARD_FAST_PATH,
        previous_effective_assessment_id="assess-old",
    )

    result = graph.invoke(state)

    assert result["current_review_outcome"] == ReviewOutcome.CARRY_FORWARD_VERIFIED
    assert result["effective_assessment_id"] == "assess-old"
    assert result["assessment_freshness"] == "verified_current"
    assert result["llm_call_count"] == 0


def test_deferred_keeps_previous_effective_assessment() -> None:
    """Verify review-deferred mode keeps the previous effective assessment.

    Returns:
        None: .
    """
    fixture = GraphFixture()
    graph = build_ai_delta_review_graph(fixture.dependencies())
    state = fixture.full_review_state().with_updates(
        review_mode=ReviewMode.REVIEW_DEFERRED,
        previous_effective_assessment_id="assess-old",
        stale_reason="news_target_incomplete",
    )

    result = graph.invoke(state)

    assert result["current_review_outcome"] == ReviewOutcome.REVIEW_DEFERRED
    assert result["effective_assessment_id"] == "assess-old"
    assert result["stale_reason"] == "news_target_incomplete"


def test_unrepairable_citation_failure_abstains_without_overwriting_effective() -> None:
    """Verify an unrepairable citation failure abstains without overwriting effective.
    Returns:.

    Returns:
        None: .
    """
    fixture = GraphFixture(
        decision_evidence_ids=("ev-invalid",),
        citation_mode="unrepairable",
    )
    graph = build_ai_delta_review_graph(fixture.dependencies())
    state = fixture.full_review_state().with_updates(
        previous_effective_assessment_id="assess-old",
    )

    result = graph.invoke(state)

    assert result["current_review_outcome"] == ReviewOutcome.ABSTAIN
    assert result["effective_assessment_id"] == "assess-old"
    assert result["repair_count"] == 1
    assert result["stale_reason"] == "citation_validation_failed"


def test_repairable_citation_removes_invalid_existing_reference_once() -> None:
    """Verify a repairable citation removes an invalid reference exactly once.

    Returns:
        None: .
    """
    fixture = GraphFixture(
        decision_evidence_ids=("ev-good", "ev-invalid"),
        citation_mode="repairable",
    )
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    assert result["current_review_outcome"] == ReviewOutcome.UPDATE_ASSESSMENT
    assert result["effective_assessment_id"].startswith("assess_")
    assert result["repair_count"] == 1
    assert result["draft_decision"]["evidence_ids"] == ("ev-good",)
    assert fixture.citation_calls == 2


def test_llm_decision_cannot_claim_verified_carry_forward() -> None:
    """Verify an LLM decision cannot claim the verified carry-forward outcome.

    Returns:
        None: .
    """
    fixture = GraphFixture(
        decision_outcome=ReviewOutcome.CARRY_FORWARD_VERIFIED,
    )
    graph = build_ai_delta_review_graph(fixture.dependencies())

    result = graph.invoke(fixture.full_review_state())

    assert result["current_review_outcome"] == ReviewOutcome.ABSTAIN
    assert "delta_decision:forbidden_outcome" in result["errors"]


class GraphFixture:
    """Reusable test fixture for building AI delta review graph dependencies.."""

    def __init__(
        self,
        *,
        shared_gap: bool = False,
        enable_supplemental: bool = True,
        failing_node: str | None = None,
        decision_evidence_ids: tuple[str, ...] = ("ev-1",),
        citation_mode: str = "valid",
        decision_outcome: ReviewOutcome = ReviewOutcome.UPDATE_ASSESSMENT,
    ) -> None:
        """Initialize the fixture with the given configuration options.

        Args:
            shared_gap: bool: .
            enable_supplemental: bool: .
            failing_node: str | None: .
            decision_evidence_ids: tuple[str, ...]: .
            citation_mode: str: .
            decision_outcome: ReviewOutcome: .

        Returns:
            None: .
        """
        self.shared_gap = shared_gap
        self.enable_supplemental = enable_supplemental
        self.failing_node = failing_node
        self.decision_evidence_ids = decision_evidence_ids
        self.citation_mode = citation_mode
        self.decision_outcome = decision_outcome
        self.citation_calls = 0
        self.audit = MemoryToolCallAuditRepository()
        self.analysis_tool_names: dict[str, tuple[str, ...]] = {}
        self.retrieval_calls = 0

    def dependencies(self) -> GraphDependencies:
        """Build graph dependencies with scoped tools and fixture handlers.

        Returns:
            GraphDependencies: .
        """
        registry = ToolDefinitionRegistry()
        registry.register(
            ToolDefinition(
                name="evidence_retrieve",
                capability=ToolCapability.EVIDENCE_RETRIEVE,
                version="evidence-retrieve-v0.2.0",
                description="Retrieve a frozen EvidencePackage.",
                input_model=RetrievalInput,
                handler=self._retrieve,
            )
        )
        registry.register(
            ToolDefinition(
                name="deterministic_valuation",
                capability=ToolCapability.DETERMINISTIC_VALUATION,
                version="deterministic-valuation-v0.2.0",
                description="Run deterministic valuation.",
                input_model=ValuationInput,
                handler=lambda payload: {"value": payload["earnings"] * payload["multiple"]},
            )
        )
        factory = ScopedToolFactory(
            tool_registry=registry,
            policy=ToolPolicyEngine(),
            audit_repository=self.audit,
        )
        return GraphDependencies(
            tool_factory=factory,
            analysis_handlers={
                name: self._analysis_handler(name)
                for name in (
                    "fundamental_analysis",
                    "valuation_analysis",
                    "risk_review",
                    "counter_argument",
                    "targeted_reanalysis",
                )
            },
            allow_supplemental_retrieval=self.enable_supplemental,
            decision_handler=self._decision,
            citation_validator=self._validate_citations,
        )

    def full_review_state(self):
        """Build an initial graph state configured for a full review.

        Returns:
            Any: .
        """
        return create_initial_state(
            graph_run_id="graph-1",
            context_snapshot_id="ctx-1",
            context_input_hash="sha256:ctx",
            scope_version_id="scope-1",
            security_id="000001.SZ",
            decision_at=DECISION_AT,
            previous_effective_assessment_id=None,
        ).with_updates(
            review_mode=ReviewMode.FULL_REVIEW,
            change_set={"initial_research": True},
        )

    def _retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle an evidence retrieval request, returning a mock package.

        Args:
            payload: dict[str, Any]: .

        Returns:
            dict[str, Any]: .
        """
        self.retrieval_calls += 1
        supplemental = bool(payload["supplemental"])
        return {
            "package_id": "pkg-supplemental" if supplemental else "pkg-initial",
            "summary": {
                "security_id": payload["security_id"],
                "evidence_ids": (["ev-2"] if supplemental else ["ev-1"]),
                "quality_status": "usable",
            },
        }

    def _analysis_handler(self, node_name: str):
        """Create an analysis handler for the given node name.

        Args:
            node_name: str: .

        Returns:
            Any: .
        """

        def handler(
            request: AnalysisRequest,
            session: ScopedToolSession,
        ) -> dict[str, Any]:
            """Inner handler closure for a single analysis branch.

            Args:
                request: AnalysisRequest: .
                session: ScopedToolSession: .

            Returns:
                dict[str, Any]: .
            """
            if node_name == self.failing_node:
                raise RuntimeError("injected branch failure")
            self.analysis_tool_names[node_name] = tuple(
                tool.name for tool in session.manifest().tools
            )
            gaps = (
                ("cash_flow_detail",)
                if self.shared_gap and node_name in {"fundamental_analysis", "risk_review"}
                else ()
            )
            if node_name == "valuation_analysis":
                valuation = session.call(
                    "deterministic_valuation",
                    {
                        "security_id": request.security_id,
                        "decision_at": request.decision_at,
                        "earnings": 2.0,
                        "multiple": 10.0,
                    },
                )
                assert valuation.success is True
            return {
                "node_name": node_name,
                "package_ids": list(request.evidence_package_ids),
                "evidence_gaps": list(gaps),
                "completed": True,
            }

        return handler

    def _decision(self, state) -> dict[str, Any]:
        """Return a deterministic decision result based on fixture configuration.

        Args:
            state: Any: .

        Returns:
            dict[str, Any]: .
        """
        del state
        return {
            "outcome": self.decision_outcome.value,
            "confidence": 0.8,
            "evidence_ids": list(self.decision_evidence_ids),
            "changed_assumptions": [{"name": "growth", "status": "updated"}],
            "llm_call_ids": ["llm-decision"],
        }

    def _validate_citations(self, draft, state) -> dict[str, Any]:
        """Validate citations against the fixture's citation mode configuration.

        Args:
            draft: Any: .
            state: Any: .

        Returns:
            dict[str, Any]: .
        """
        del state
        self.citation_calls += 1
        evidence_ids = tuple(draft["evidence_ids"])
        if self.citation_mode == "valid":
            return {
                "valid": True,
                "repairable": False,
                "invalid_evidence_ids": [],
            }
        if self.citation_mode == "repairable" and "ev-invalid" not in evidence_ids:
            return {
                "valid": True,
                "repairable": False,
                "invalid_evidence_ids": [],
            }
        return {
            "valid": False,
            "repairable": self.citation_mode == "repairable",
            "invalid_evidence_ids": ["ev-invalid"],
            "reason": "citation mismatch",
        }
