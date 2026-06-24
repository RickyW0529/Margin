"""High-level research service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from margin.news.models import ensure_utc
from margin.research.delta_repository import (
    MemoryResearchDeltaRepository,
    ResearchDeltaRepository,
    ResearchDeltaReview,
    SQLAlchemyResearchDeltaRepository,
)
from margin.research.execution.llm_service import LLMCallAuditRepository
from margin.research.graph.builder import GraphDependencies, build_ai_delta_review_graph
from margin.research.graph.nodes.analysis import AnalysisHandler, AnalysisRequest
from margin.research.graph.nodes.context import (
    CarryForwardRuleNode,
    GraphContextSnapshot,
)
from margin.research.graph.nodes.decision import (
    CitationValidationHandler,
    DecisionHandler,
)
from margin.research.graph.state import (
    AIDeltaGraphState,
    ReviewMode,
    ReviewOutcome,
    create_initial_state,
)
from margin.research.llm import LLMProvider
from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.research.tools.executor import (
    MemoryToolCallAuditRepository,
    ToolCallAuditRepository,
)
from margin.research.tools.factory import ScopedToolFactory, ScopedToolSession
from margin.research.tools.policy import ToolPolicyEngine
from margin.storage.database import SessionFactory
from margin.valuation_discovery.db_models import ResearchContextSnapshotRow

if TYPE_CHECKING:
    from margin.valuation_discovery.analysis_mart import AnalysisMartRepository


class ResearchContextSnapshot(BaseModel):
    """Frozen context consumed by the v0.2 AI delta review graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_snapshot_id: str
    security_id: str
    scope_version_id: str
    decision_at: datetime
    payload_hash: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        """Normalize context timestamps to UTC."""
        return ensure_utc(value) if value is not None else None


class AIDeltaReviewResult(BaseModel):

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_run_id: str
    context_snapshot_id: str
    security_id: str
    decision_at: datetime
    review_mode: ReviewMode | None
    current_review_outcome: ReviewOutcome
    effective_assessment_id: str | None = None
    assessment_freshness: str | None = None
    stale_reason: str | None = None
    confidence: float = 0.0
    conclusion: str = ""
    valuation_view: str = "uncertain"
    evidence_package_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    changed_assumptions: tuple[dict[str, Any], ...] = ()
    llm_call_count: int = 0
    tool_call_count: int = 0
    review_id: str


class ResearchContextRepository(Protocol):

    def get_context_snapshot(
        self,
        context_snapshot_id: str,
    ) -> ResearchContextSnapshot | None:
        """Load one frozen context snapshot."""
        ...


class MemoryResearchContextRepository:

    def __init__(self) -> None:
        """Initialize an empty repository."""
        self._snapshots: dict[str, ResearchContextSnapshot] = {}

    def add(self, snapshot: ResearchContextSnapshot) -> None:
        """Persist a snapshot by immutable ID."""
        existing = self._snapshots.get(snapshot.context_snapshot_id)
        if existing is not None and existing != snapshot:
            raise ValueError("conflicting research context snapshot")
        self._snapshots[snapshot.context_snapshot_id] = snapshot

    def get_context_snapshot(
        self,
        context_snapshot_id: str,
    ) -> ResearchContextSnapshot | None:
        """Load one frozen context snapshot."""
        return self._snapshots.get(context_snapshot_id)


class SQLAlchemyResearchContextRepository:

    def __init__(self, session_factory: SessionFactory) -> None:
        """Initialize the repository."""
        self._session_factory = session_factory

    def get_context_snapshot(
        self,
        context_snapshot_id: str,
    ) -> ResearchContextSnapshot | None:
        """Load one frozen context snapshot."""
        with self._session_factory() as session:
            row = session.get(ResearchContextSnapshotRow, context_snapshot_id)
            if row is None:
                return None
            return ResearchContextSnapshot(
                context_snapshot_id=row.context_snapshot_id,
                security_id=row.security_id,
                scope_version_id=row.scope_version_id,
                decision_at=row.decision_at,
                payload_hash=row.payload_hash,
                payload=dict(row.payload_json),
                created_at=row.created_at,
            )


class EvidenceRetrieveInput(BaseModel):

    security_id: str
    decision_at: datetime
    questions: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()
    supplemental: bool = False

    model_config = ConfigDict(frozen=True, extra="forbid")


class ResearchService:

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        context_repository: ResearchContextRepository | None = None,
        delta_repository: ResearchDeltaRepository | None = None,
        session_factory: SessionFactory | None = None,
        v02_tool_factory: ScopedToolFactory | None = None,
        v02_analysis_handlers: Mapping[str, AnalysisHandler] | None = None,
        v02_decision_handler: DecisionHandler | None = None,
        v02_citation_validator: CitationValidationHandler | None = None,
        v02_checkpointer: Any | None = None,
        v02_llm_audit_repository: LLMCallAuditRepository | None = None,
        v02_tool_audit_repository: ToolCallAuditRepository | None = None,
        analysis_mart_repository: AnalysisMartRepository | None = None,
    ) -> None:
        """Initialize the research service.

        Args:
            llm_provider: Optional LLM provider used for v0.2 graph nodes.
        """
        self._llm = llm_provider
        self._context_repository: ResearchContextRepository = (
            context_repository
            or (
                SQLAlchemyResearchContextRepository(session_factory)
                if session_factory is not None
                else MemoryResearchContextRepository()
            )
        )
        self._delta_repository: ResearchDeltaRepository = (
            delta_repository
            or (
                SQLAlchemyResearchDeltaRepository(session_factory)
                if session_factory is not None
                else MemoryResearchDeltaRepository()
            )
        )
        self._session_factory = session_factory
        self._v02_tool_factory = v02_tool_factory
        self._v02_analysis_handlers = dict(v02_analysis_handlers or {})
        self._v02_decision_handler = v02_decision_handler
        self._v02_citation_validator = v02_citation_validator
        self._v02_checkpointer = v02_checkpointer
        self._v02_llm_audit_repository = v02_llm_audit_repository
        self._v02_tool_audit_repository = v02_tool_audit_repository
        if analysis_mart_repository is not None:
            self._analysis_mart_repository = analysis_mart_repository
        elif session_factory is not None:
            from margin.valuation_discovery.analysis_mart import (
                SQLAlchemyAnalysisMartRepository,
            )

            self._analysis_mart_repository = SQLAlchemyAnalysisMartRepository(
                session_factory
            )
        else:
            self._analysis_mart_repository = None

    def run_delta_review(self, context_snapshot_id: str) -> AIDeltaReviewResult:
        """Run the v0.2 AI delta-review graph for one frozen context snapshot."""
        context = self._context_repository.get_context_snapshot(context_snapshot_id)
        if context is None:
            raise KeyError(f"research context snapshot not found: {context_snapshot_id}")
        routed_state = self._routed_initial_state(context)
        graph_run_id = routed_state.graph_run_id
        existing_review = self._delta_repository.get_review_by_graph_run(
            graph_run_id
        )
        if existing_review is not None:
            return _dto_from_review(existing_review)
        if self._session_factory is not None:
            self._ensure_graph_run_row(routed_state)
        analysis_handlers = self._v02_analysis_handlers
        decision_handler = self._v02_decision_handler
        citation_validator = self._v02_citation_validator
        if self._llm is not None and (
            analysis_handlers is None
            or decision_handler is None
            or citation_validator is None
        ):
            from margin.research.execution.llm_service import LLMService
            from margin.research.production_graph import (
                build_production_analysis_handlers,
                build_production_citation_validator,
                build_production_decision_handler,
            )

            llm_service = LLMService(
                self._llm,
                audit_repository=self._v02_llm_audit_repository,
            )
            analysis_handlers = (
                analysis_handlers
                or build_production_analysis_handlers(
                    context=context,
                    llm_service=llm_service,
                )
            )
            decision_handler = (
                decision_handler
                or build_production_decision_handler(
                    context=context,
                    llm_service=llm_service,
                )
            )
            citation_validator = (
                citation_validator
                or build_production_citation_validator(context)
            )
        graph = build_ai_delta_review_graph(
            GraphDependencies(
                tool_factory=self._v02_tool_factory
                or _default_tool_factory(
                    context,
                    audit_repository=self._v02_tool_audit_repository,
                    analysis_mart_repository=self._analysis_mart_repository,
                ),
                analysis_handlers=analysis_handlers
                or _default_analysis_handlers(context),
                decision_handler=decision_handler or _default_decision_handler,
                citation_validator=citation_validator
                or _default_citation_validator,
                checkpointer=self._v02_checkpointer,
            )
        )
        config = (
            {
                "configurable": {
                    "thread_id": graph_run_id,
                    "checkpoint_ns": "",
                    "identity_hash": routed_state.identity_hash,
                }
            }
            if self._v02_checkpointer is not None
            else None
        )
        raw_result = graph.invoke(routed_state, config=config)
        result = _dto_from_graph_result(context, raw_result)
        self._delta_repository.persist_final_review(
            _review_from_result(
                result,
                graph_result=raw_result,
                context=context,
            )
        )
        return result

    def _routed_initial_state(
        self,
        context: ResearchContextSnapshot,
    ) -> AIDeltaGraphState:
        """_routed_initial_state.

        Args:
        context (ResearchContextSnapshot): Description.

        Returns:
        AIDeltaGraphState: Description.
        """
        payload = context.payload
        initial_state = create_initial_state(
            graph_run_id=_graph_run_id(context),
            context_snapshot_id=context.context_snapshot_id,
            context_input_hash=context.payload_hash,
            scope_version_id=context.scope_version_id,
            security_id=context.security_id,
            decision_at=context.decision_at,
            quant_input_snapshot_id=_optional_str(payload, "quant_input_snapshot_id"),
            current_quant_result_id=_optional_str(payload, "current_quant_result_id"),
            previous_effective_assessment_id=_optional_str(
                payload,
                "previous_effective_assessment_id",
            ),
            news_context_bundle_id=_optional_str(payload, "news_context_bundle_id"),
        )
        context_view = GraphContextSnapshot(
            context_snapshot_id=context.context_snapshot_id,
            input_hash=context.payload_hash,
            scope_version_id=context.scope_version_id,
            security_id=context.security_id,
            decision_at=context.decision_at,
            quant_input_valid=bool(payload.get("quant_input_valid", False)),
            pit_valid=bool(payload.get("pit_valid", False)),
            news_target_complete=bool(payload.get("news_target_complete", False)),
            provider_budget_available=bool(
                payload.get("provider_budget_available", False)
            ),
            review_due=bool(payload.get("review_due", False)),
            material_quant_change=bool(payload.get("material_quant_change", False)),
            material_valuation_change=bool(
                payload.get("material_valuation_change", False)
            ),
            material_news_change=bool(payload.get("material_news_change", False)),
            assumption_change=bool(payload.get("assumption_change", False)),
            ambiguous_change=bool(payload.get("ambiguous_change", False)),
        )
        return CarryForwardRuleNode(context_view).run(initial_state)

    def _ensure_graph_run_row(self, state: AIDeltaGraphState) -> None:
        """_ensure_graph_run_row.

        Args:
        state (AIDeltaGraphState): Description.

        Raises:
        ValueError: Description.
        """
        from margin.research.db_models import AIGraphRunRow

        now = datetime.now(UTC)
        assert self._session_factory is not None
        with self._session_factory.begin() as session:
            existing = session.get(AIGraphRunRow, state.graph_run_id)
            if existing is not None:
                if existing.identity_hash != state.identity_hash:
                    raise ValueError("conflicting graph run identity")
                return
            session.add(
                AIGraphRunRow(
                    graph_run_id=state.graph_run_id,
                    graph_version=state.graph_version,
                    context_snapshot_id=state.context_snapshot_id,
                    context_input_hash=state.context_input_hash,
                    identity_hash=state.identity_hash,
                    state_hash=_hash_json(state.model_dump(mode="json")),
                    scope_version_id=state.scope_version_id,
                    security_id=state.security_id,
                    decision_at=state.decision_at,
                    status="running",
                    review_mode=(
                        state.review_mode.value if state.review_mode else None
                    ),
                    llm_call_count=0,
                    tool_call_count=0,
                    retrieval_count=0,
                    repair_count=0,
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )


def _default_tool_factory(
    context: ResearchContextSnapshot,
    *,
    audit_repository: ToolCallAuditRepository | None = None,
    analysis_mart_repository: AnalysisMartRepository | None = None,
) -> ScopedToolFactory:
    """_default_tool_factory.

    Args:
        context (ResearchContextSnapshot): Description.

    Returns:
        ScopedToolFactory: Description.
    """
    registry = ToolDefinitionRegistry()
    registry.register(
        ToolDefinition(
            name="evidence_retrieve",
            capability=ToolCapability.EVIDENCE_RETRIEVE,
            version="evidence-retrieve-v0.2.0",
            description="Retrieve frozen evidence package references from context.",
            input_model=EvidenceRetrieveInput,
            handler=lambda payload: _retrieve_evidence_from_context(context, payload),
        )
    )
    if analysis_mart_repository is not None:
        from margin.research.analysis_tools import register_analysis_mart_tools

        register_analysis_mart_tools(
            registry,
            repository=analysis_mart_repository,
        )
    return ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
        audit_repository=audit_repository or MemoryToolCallAuditRepository(),
    )


def _retrieve_evidence_from_context(
    context: ResearchContextSnapshot,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """_retrieve_evidence_from_context.

    Args:
        context (ResearchContextSnapshot): Description.
        payload (dict[str, Any]): Description.

    Returns:
        dict[str, Any]: Description.

    Raises:
        RuntimeError: Description.
    """
    evidence_ids = tuple(
        str(value) for value in context.payload.get("evidence_ids", ())
    )
    package_id_value = context.payload.get(
        "supplemental_evidence_package_id"
        if payload.get("supplemental")
        else "evidence_package_id"
    )
    if not package_id_value or not evidence_ids:
        raise RuntimeError("frozen evidence package is unavailable")
    package_id = str(package_id_value)
    return {
        "package_id": package_id,
        "summary": {
            "security_id": context.security_id,
            "evidence_ids": list(evidence_ids),
            "quality_status": context.payload.get("evidence_quality_status", "usable"),
            "evidence_blocks": list(
                context.payload.get("evidence_blocks", ())
            ),
        },
    }


def _default_analysis_handlers(
    context: ResearchContextSnapshot,
) -> dict[str, Callable[[AnalysisRequest, ScopedToolSession], dict[str, Any]]]:
    """_default_analysis_handlers.

    Args:
        context (ResearchContextSnapshot): Description.

    Returns:
        dict[str, Callable[[AnalysisRequest, ScopedToolSession], dict[str, Any]]]: Description.
    """
    return {
        node_name: _analysis_handler(context, node_name)
        for node_name in (
            "fundamental_analysis",
            "valuation_analysis",
            "risk_review",
            "counter_argument",
            "targeted_reanalysis",
        )
    }


def _analysis_handler(
    context: ResearchContextSnapshot,
    node_name: str,
) -> Callable[[AnalysisRequest, ScopedToolSession], dict[str, Any]]:
    """_analysis_handler.

    Args:
        context (ResearchContextSnapshot): Description.
        node_name (str): Description.

    Returns:
        Callable[[AnalysisRequest, ScopedToolSession], dict[str, Any]]: Description.
    """
    def handler(
        request: AnalysisRequest,
        session: ScopedToolSession,
    ) -> dict[str, Any]:
        """handler.

        Args:
        request (AnalysisRequest): Description.
        session (ScopedToolSession): Description.

        Returns:
        dict[str, Any]: Description.
        """
        del session
        forced_gaps = tuple(
            str(value)
            for value in context.payload.get("evidence_gaps_by_node", {}).get(
                node_name,
                (),
            )
        )
        return {
            "node_name": node_name,
            "security_id": request.security_id,
            "package_ids": list(request.evidence_package_ids),
            "evidence_gaps": list(forced_gaps),
            "completed": True,
            "llm_call_ids": [f"llm-{node_name}-{context.context_snapshot_id}"],
        }

    return handler


def _default_decision_handler(state: AIDeltaGraphState) -> dict[str, Any]:
    """_default_decision_handler.

    Args:
        state (AIDeltaGraphState): Description.

    Returns:
        dict[str, Any]: Description.
    """
    evidence_ids: list[str] = []
    for package in state.node_outputs.get("evidence_packages", {}).values():
        summary = package.get("summary", {}) if isinstance(package, dict) else {}
        evidence_ids.extend(str(value) for value in summary.get("evidence_ids", ()))
    if not evidence_ids:
        evidence_ids = list(state.evidence_package_ids)
    return {
        "outcome": ReviewOutcome.UPDATE_ASSESSMENT.value,
        "confidence": 0.7,
        "evidence_ids": evidence_ids,
        "changed_assumptions": [{"name": "context", "status": "reviewed"}],
        "llm_call_ids": [f"llm-delta-decision-{state.graph_run_id}"],
    }


def _default_citation_validator(
    draft: dict[str, Any],
    state: AIDeltaGraphState,
) -> dict[str, Any]:
    """_default_citation_validator.

    Args:
        draft (dict[str, Any]): Description.
        state (AIDeltaGraphState): Description.

    Returns:
        dict[str, Any]: Description.
    """
    del state
    return {
        "valid": bool(draft.get("evidence_ids")),
        "repairable": False,
        "invalid_evidence_ids": [],
        "reason": None if draft.get("evidence_ids") else "no_evidence_ids",
    }


def _dto_from_graph_result(
    context: ResearchContextSnapshot,
    graph_result: Mapping[str, Any],
) -> AIDeltaReviewResult:
    """_dto_from_graph_result.

    Args:
        context (ResearchContextSnapshot): Description.
        graph_result (Mapping[str, Any]): Description.

    Returns:
        AIDeltaReviewResult: Description.
    """
    outcome = _review_outcome(graph_result.get("current_review_outcome"))
    final_result = graph_result.get("final_result", {})
    evidence_package_ids = tuple(
        str(value) for value in graph_result.get("evidence_package_ids", ())
    )
    evidence_ids = tuple(str(value) for value in final_result.get("evidence_ids", ()))
    changed_assumptions = tuple(
        dict(value) for value in final_result.get("changed_assumptions", ())
    )
    result_hash = _hash_json(
        {
            "graph_run_id": graph_result["graph_run_id"],
            "outcome": outcome.value,
            "effective_assessment_id": graph_result.get("effective_assessment_id"),
            "evidence_ids": evidence_ids,
            "changed_assumptions": changed_assumptions,
        }
    )
    review_id = "review_" + result_hash.removeprefix("sha256:")[:24]
    return AIDeltaReviewResult(
        graph_run_id=str(graph_result["graph_run_id"]),
        context_snapshot_id=context.context_snapshot_id,
        security_id=context.security_id,
        decision_at=context.decision_at,
        review_mode=(
            ReviewMode(graph_result["review_mode"])
            if graph_result.get("review_mode")
            else None
        ),
        current_review_outcome=outcome,
        effective_assessment_id=graph_result.get("effective_assessment_id"),
        assessment_freshness=graph_result.get("assessment_freshness"),
        stale_reason=graph_result.get("stale_reason"),
        confidence=float(final_result.get("confidence", 0.0)),
        conclusion=str(final_result.get("conclusion", "")),
        valuation_view=str(final_result.get("valuation_view", "uncertain")),
        evidence_package_ids=evidence_package_ids,
        evidence_ids=evidence_ids,
        changed_assumptions=changed_assumptions,
        llm_call_count=int(graph_result.get("llm_call_count", 0)),
        tool_call_count=len(tuple(graph_result.get("tool_call_ids", ()))),
        review_id=review_id,
    )


def _dto_from_review(review: ResearchDeltaReview) -> AIDeltaReviewResult:
    """Return the public DTO for an already-persisted terminal review."""
    return AIDeltaReviewResult(
        graph_run_id=review.graph_run_id,
        context_snapshot_id=review.context_snapshot_id,
        security_id=review.security_id,
        decision_at=review.decision_at,
        review_mode=review.review_mode,
        current_review_outcome=review.outcome,
        effective_assessment_id=review.effective_assessment_id,
        assessment_freshness=review.assessment_freshness,
        stale_reason=review.stale_reason,
        confidence=review.confidence,
        conclusion=review.conclusion,
        valuation_view=review.valuation_view,
        evidence_ids=review.evidence_ids,
        changed_assumptions=review.changed_assumptions,
        llm_call_count=review.llm_call_count,
        tool_call_count=review.tool_call_count,
        review_id=review.review_id,
    )


def _review_from_result(
    result: AIDeltaReviewResult,
    *,
    graph_result: Mapping[str, Any],
    context: ResearchContextSnapshot,
) -> ResearchDeltaReview:
    """_review_from_result.

    Args:
        result (AIDeltaReviewResult): Description.

    Returns:
        ResearchDeltaReview: Description.
    """
    return ResearchDeltaReview(
        review_id=result.review_id,
        graph_run_id=result.graph_run_id,
        context_snapshot_id=result.context_snapshot_id,
        security_id=result.security_id,
        decision_at=result.decision_at,
        review_mode=result.review_mode or ReviewMode.ABSTAIN,
        outcome=result.current_review_outcome,
        previous_effective_assessment_id=_optional_str(
            context.payload,
            "previous_effective_assessment_id",
        ),
        effective_assessment_id=result.effective_assessment_id,
        assessment_freshness=result.assessment_freshness,
        stale_reason=result.stale_reason,
        confidence=result.confidence,
        conclusion=result.conclusion,
        valuation_view=result.valuation_view,
        changed_assumptions=result.changed_assumptions,
        evidence_ids=result.evidence_ids,
        model_versions=dict(context.payload.get("model_versions", {})),
        prompt_versions=dict(context.payload.get("prompt_versions", {})),
        tool_versions=dict(context.payload.get("tool_versions", {})),
        llm_call_count=result.llm_call_count,
        tool_call_count=result.tool_call_count,
        result_hash=_hash_json(graph_result.get("final_result", {})),
        created_at=datetime.now(UTC),
    )


def _graph_run_id(context: ResearchContextSnapshot) -> str:
    """_graph_run_id.

    Args:
        context (ResearchContextSnapshot): Description.

    Returns:
        str: Description.
    """
    return "graph_" + _hash_json(
        {
            "context_snapshot_id": context.context_snapshot_id,
            "payload_hash": context.payload_hash,
        }
    ).removeprefix("sha256:")[:24]


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    """_optional_str.

    Args:
        payload (Mapping[str, Any]): Description.
        key (str): Description.

    Returns:
        str | None: Description.
    """
    value = payload.get(key)
    return str(value) if value not in {None, ""} else None


def _review_outcome(value: Any) -> ReviewOutcome:
    """_review_outcome.

    Args:
        value (Any): Description.

    Returns:
        ReviewOutcome: Description.
    """
    if isinstance(value, ReviewOutcome):
        return value
    if value is None:
        return ReviewOutcome.ABSTAIN
    return ReviewOutcome(str(value))


def _hash_json(value: Any) -> str:
    """_hash_json.

    Args:
        value (Any): Description.

    Returns:
        str: Description.
    """
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
