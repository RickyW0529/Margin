"""Production valuation publisher behavior tests.

This module validates that the valuation publisher adapter uses persisted AI
reviews without inventing identifiers, is replay-idempotent, handles
first-run abstention correctly, and refreshes the dashboard from persisted
pointers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agents.workers.dashboard_publisher_worker import DashboardPublisherWorker
from margin.agents.workers.recommendation_workers import (
    FusedRecommendation,
    RecommendationEvidenceRef,
    RecommendationFusionPolicy,
    RecommendationFusionResult,
)
from margin.dashboard.models import DashboardFilters, DashboardSort
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardQueryService
from margin.research.delta_repository import (
    MemoryResearchDeltaRepository,
    ResearchDeltaReview,
)
from margin.research.graph.state import ReviewMode, ReviewOutcome
from margin.valuation_discovery.adapters import ValuationPublisherAdapter
from margin.valuation_discovery.assessments import EffectiveAssessmentService
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.repository import MemoryValuationDiscoveryRepository

DECISION_AT = datetime(2026, 6, 23, 8, 30, tzinfo=UTC)


@dataclass(frozen=True)
class ReviewSummary:
    """Minimal persisted-review summary consumed by the publisher.."""

    review_ids: tuple[str, ...]
    context_snapshot_ids: tuple[str, ...] = ()


def test_update_review_publishes_real_assessment_evidence_and_pointer() -> None:
    """Verify the publisher uses the persisted AI review without inventing identifiers.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    review = _review(
        review_id="review-update",
        outcome=ReviewOutcome.UPDATE_ASSESSMENT,
        previous_assessment_id="assessment-old",
        effective_assessment_id="assessment-new",
        conclusion="估值仍低于可比公司，但现金流风险需要持续复核。",
        evidence_ids=("evidence-1", "evidence-2"),
    )
    reviews.persist_final_review(review)
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
    )

    result = publisher.publish(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        review_summary=ReviewSummary(review_ids=(review.review_id,)),
    )

    assert result.assessment_count == 1
    assert result.pointer_count == 1
    assert result.skipped_review_ids == ()
    assessment = valuations.get_valuation_assessment("assessment-new")
    assert assessment is not None
    assert assessment.security_id == "000001.SZ"
    assert assessment.conclusion == review.conclusion
    assert assessment.evidence_refs == review.evidence_ids
    assert assessment.valuation_model == "ai_delta_review_v0.2"
    assert [
        edge.evidence_id for edge in valuations.list_valuation_assessment_evidence("assessment-new")
    ] == ["evidence-1", "evidence-2"]
    [pointer] = valuations.list_effective_assessment_pointers()
    assert pointer.effective_assessment_id == "assessment-new"
    assert pointer.previous_assessment_id == "assessment-old"
    assert pointer.effective_from == DECISION_AT


def test_publisher_replay_is_idempotent() -> None:
    """Verify retrying the publication step does not duplicate immutable records.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    review = _review(
        review_id="review-replay",
        outcome=ReviewOutcome.INVALIDATE,
        previous_assessment_id="assessment-old",
        effective_assessment_id="assessment-invalid",
        conclusion="核心假设失效。",
        evidence_ids=("evidence-3",),
    )
    reviews.persist_final_review(review)
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
    )
    summary = ReviewSummary(review_ids=(review.review_id,))

    first = publisher.publish(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        review_summary=summary,
    )
    second = publisher.publish(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        review_summary=summary,
    )

    assert first == second
    assert len(valuations.list_valuation_assessments()) == 1
    assert len(valuations.list_effective_assessment_pointers()) == 1
    assert len(valuations.list_valuation_assessment_evidence("assessment-invalid")) == 1


def test_abstain_without_previous_assessment_does_not_create_fake_pointer() -> None:
    """Verify a first-run abstention remains review-only until an assessment exists.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    review = _review(
        review_id="review-first-abstain",
        outcome=ReviewOutcome.ABSTAIN,
        previous_assessment_id=None,
        effective_assessment_id=None,
        conclusion="证据不足，无法形成有效估值结论。",
        evidence_ids=(),
    )
    reviews.persist_final_review(review)
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
    )

    result = publisher.publish(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        review_summary=ReviewSummary(review_ids=(review.review_id,)),
    )

    assert result.assessment_count == 0
    assert result.pointer_count == 0
    assert result.skipped_review_ids == ("review-first-abstain",)
    assert valuations.list_valuation_assessments() == []
    assert valuations.list_effective_assessment_pointers() == []


def test_dashboard_refresh_reports_persisted_effective_projection() -> None:
    """Verify dashboard refresh reflects persisted pointers rather than a no-op string.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    review = _review(
        review_id="review-dashboard",
        outcome=ReviewOutcome.UPDATE_ASSESSMENT,
        previous_assessment_id=None,
        effective_assessment_id="assessment-dashboard",
        conclusion="形成首个有效结论。",
        evidence_ids=("evidence-4",),
    )
    reviews.persist_final_review(review)
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
    )
    publisher.publish(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        review_summary=ReviewSummary(review_ids=(review.review_id,)),
    )

    projection = publisher.refresh_dashboard(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
    )

    assert projection.scope_version_id == "scope-1"
    assert projection.effective_assessment_count == 1
    assert projection.as_of == DECISION_AT


def test_dashboard_refresh_publishes_latest_quant_projection_items() -> None:
    """Verify refresh writes visible quant results into the dashboard repository.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    dashboard = MemoryDashboardRepository()
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
        dashboard_repository=dashboard,
    )

    projection = publisher.refresh_dashboard(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        quant_results=(
            _quant_result(
                "000001.SZ",
                score=88,
                screening_status=ScreeningStatus.PASS,
                target_weight=0.32,
            ),
            _quant_result(
                "000002.SZ",
                score=76,
                screening_status=ScreeningStatus.NEAR_THRESHOLD,
                review_required=True,
                review_reasons=("接近阈值",),
            ),
            _quant_result(
                "000003.SZ",
                score=20,
                screening_status=ScreeningStatus.REJECT,
            ),
        ),
    )

    response = dashboard.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=None,
        limit=20,
    )
    assert projection.dashboard_run_id is not None
    assert projection.visible_item_count == 2
    assert [item.security_id for item in response.items] == ["000001.SZ", "000002.SZ"]
    assert response.items[0].screening_status == "pass"
    assert response.items[0].target_weight == 0.32
    assert response.items[0].adjusted_weight == 0.32
    assert response.items[0].agent_adjustment["source"] == "quant_default"
    assert response.items[1].target_weight is None
    assert response.items[1].adjusted_weight is None
    assert response.items[1].screening_status == "near_threshold"
    assert response.items[1].review_required is True


def test_dashboard_refresh_publishes_fusion_lineage_and_portfolio_summary() -> None:
    """Fusion projection is the terminal source for weights, reasons, and evidence."""
    dashboard = MemoryDashboardRepository()
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=MemoryResearchDeltaRepository(),
        valuation_repository=MemoryValuationDiscoveryRepository(),
        dashboard_repository=dashboard,
    )
    fusion = RecommendationFusionResult(
        artifact_id="fusion-1",
        orchestration_run_id="run-1",
        quant_run_id="quant-1",
        max_stock_exposure=0.8,
        policy=RecommendationFusionPolicy(),
        stock_weight=0.8,
        cash_weight=0.2,
        recommendations=(
            FusedRecommendation(
                security_id="000001.SZ",
                target_weight=0.7,
                adjusted_weight=0.8,
                quant_score=82.0,
                fusion_confidence=0.88,
                quant_contribution=0.7,
                catalyst_contribution=0.1,
                sources=("ml_quant", "earnings_catalyst"),
                reasons=("量化通过", "财报需求增长"),
                risk_flags=("high_leverage",),
                evidence=(
                    RecommendationEvidenceRef(source_type="rag", source_id="ev-1"),
                    RecommendationEvidenceRef(
                        source_type="warehouse_quant_result",
                        source_id="qres-1",
                    ),
                    RecommendationEvidenceRef(
                        source_type="websearch",
                        source_id="web-1",
                        title="反证搜索",
                        url="https://example.com/counter",
                        excerpt="未发现足以推翻原结论的信息。",
                    ),
                ),
            ),
        ),
    )

    projection = publisher.refresh_dashboard(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        recommendation_result=fusion,
    )

    response = dashboard.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=None,
        limit=20,
    )
    assert projection.visible_item_count == 1
    assert response.portfolio_summary is not None
    assert response.portfolio_summary.stock_weight == 0.8
    assert response.portfolio_summary.cash_weight == 0.2
    [item] = response.items
    assert item.target_weight == 0.7
    assert item.adjusted_weight == 0.8
    assert item.final_score == 82.0
    assert item.confidence == 0.88
    assert item.risk_flags == ("high_leverage",)
    assert item.effective_assessment_id is None
    assert item.assessment_freshness == "missing"
    assert item.agent_adjustment["sources"] == ["ml_quant", "earnings_catalyst"]
    assert item.agent_adjustment["evidence_ids"] == ["ev-1", "qres-1"]
    assert item.agent_adjustment["fusion_policy"]["catalyst_only_max_weight"] == 0.02

    [stored_item] = dashboard.list_items(projection.dashboard_run_id or "")
    assert stored_item.workflow_run_id == "quant-1"
    assert stored_item.snapshot_id is None

    detail = DashboardQueryService(
        dashboard,
        detail_context_loader=lambda projected_item, _run: {
            "effective_assessment": {
                "assessment_id": "assess-real-1",
                "freshness": "current",
                "stale_reason": None,
            },
            "evidence": [
                {
                    "evidence_id": "evt-context",
                    "source_kind": "document",
                    "detail_url": "/api/v1/evidence/evt-context",
                    "source_level": "L1",
                    "locator": "context document",
                }
            ],
            "versions": {"context_quant_run_id": projected_item.workflow_run_id},
        },
    ).get_item_detail_v2(stored_item.item_id)
    assert detail.effective_assessment["assessment_id"] == "assess-real-1"
    assert detail.versions["context_quant_run_id"] == "quant-1"
    assert [row["evidence_id"] for row in detail.evidence] == [
        "ev-1",
        "qres-1",
        "web-1",
        "evt-context",
    ]
    assert detail.evidence[1]["source_kind"] == "quant_result"
    assert detail.evidence[2]["source_url"] == "https://example.com/counter"
    assert detail.evidence[2]["detail_url"] is None


def test_catalyst_only_dashboard_item_has_no_quant_score() -> None:
    """Catalyst-only research keeps its confidence without inventing ML output."""
    dashboard = MemoryDashboardRepository()
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=MemoryResearchDeltaRepository(),
        valuation_repository=MemoryValuationDiscoveryRepository(),
        dashboard_repository=dashboard,
    )
    fusion = RecommendationFusionResult(
        artifact_id="fusion-catalyst-only",
        orchestration_run_id="run-catalyst-only",
        quant_run_id="quant-catalyst-only",
        max_stock_exposure=0.8,
        policy=RecommendationFusionPolicy(),
        stock_weight=0.02,
        cash_weight=0.98,
        recommendations=(
            FusedRecommendation(
                security_id="000003.SZ",
                target_weight=0.02,
                adjusted_weight=0.02,
                quant_score=None,
                fusion_confidence=0.91,
                quant_contribution=0.0,
                catalyst_contribution=0.91,
                sources=("earnings_catalyst",),
                reasons=("财报供不应求",),
                evidence=(RecommendationEvidenceRef(source_type="rag", source_id="ev-3"),),
            ),
        ),
    )

    publisher.refresh_dashboard(
        scope_version_id="scope-catalyst-only",
        decision_at=DECISION_AT,
        recommendation_result=fusion,
    )
    response = dashboard.list_research_candidates_v2(
        scope_version_id="scope-catalyst-only",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=None,
        limit=20,
    )

    [item] = response.items
    assert item.final_score is None
    assert item.confidence == 0.91
    assert item.agent_adjustment["quant_score"] is None
    assert item.agent_adjustment["fusion_confidence"] == 0.91


def test_dashboard_refresh_can_publish_agent_adjusted_projection() -> None:
    """Publisher can let the v1 dashboard worker remove risky names.

    Returns:
        None: .
    """
    reviews = MemoryResearchDeltaRepository()
    valuations = MemoryValuationDiscoveryRepository()
    dashboard = MemoryDashboardRepository()
    context_store = MemoryAgentContextStore()
    publisher = ValuationPublisherAdapter(
        assessment_service=EffectiveAssessmentService(),
        review_repository=reviews,
        valuation_repository=valuations,
        dashboard_repository=dashboard,
        stock_analyst_agent=DashboardPublisherWorker(
            write_context_artifact=context_store.add_artifact,
            dashboard_repository=dashboard,
        ),
    )

    projection = publisher.refresh_dashboard(
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_run_id="quant-1",
        quant_results=(
            _quant_result(
                "000001.SZ",
                score=90,
                screening_status=ScreeningStatus.PASS,
                target_weight=0.50,
            ),
            _quant_result(
                "000002.SZ",
                score=88,
                screening_status=ScreeningStatus.PASS,
                target_weight=0.50,
            ),
            _quant_result(
                "000003.SZ",
                score=86,
                screening_status=ScreeningStatus.PASS,
                risk_flags=("short_term_overheat",),
                target_weight=0.20,
            ),
        ),
    )

    response = dashboard.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="symbol", direction="asc"),
        cursor=None,
        limit=20,
    )
    assert projection.dashboard_run_id == "dr_agent_ar_dashboard_quant-1"
    assert projection.visible_item_count == 2
    assert [item.security_id for item in response.items] == ["000001.SZ", "000002.SZ"]
    assert sum(item.adjusted_weight or 0.0 for item in response.items) == 0.80
    assert response.items[0].agent_adjustment["source"] == "DashboardPublisherWorker"
    artifact = context_store.get_artifact("ctx_ar_dashboard_quant-1_portfolio_adjustment")
    assert artifact is not None
    assert artifact.payload_json["removed_security_ids"] == ["000003.SZ"]


def _review(
    *,
    review_id: str,
    outcome: ReviewOutcome,
    previous_assessment_id: str | None,
    effective_assessment_id: str | None,
    conclusion: str,
    evidence_ids: tuple[str, ...],
) -> ResearchDeltaReview:
    """Build one deterministic ResearchDeltaReview for publisher adapter tests.

    Args:
        review_id: str: .
        outcome: ReviewOutcome: .
        previous_assessment_id: str | None: .
        effective_assessment_id: str | None: .
        conclusion: str: .
        evidence_ids: tuple[str, ...]: .

    Returns:
        ResearchDeltaReview: .
    """

    return ResearchDeltaReview(
        review_id=review_id,
        graph_run_id=f"graph-{review_id}",
        context_snapshot_id=f"context-{review_id}",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        review_mode=ReviewMode.DELTA_REVIEW,
        outcome=outcome,
        previous_effective_assessment_id=previous_assessment_id,
        effective_assessment_id=effective_assessment_id,
        assessment_freshness=(
            "current"
            if outcome
            in {
                ReviewOutcome.UPDATE_ASSESSMENT,
                ReviewOutcome.DOWNGRADE_CONFIDENCE,
                ReviewOutcome.INVALIDATE,
            }
            else "stale"
        ),
        stale_reason=("insufficient_evidence" if outcome is ReviewOutcome.ABSTAIN else None),
        confidence=0.72,
        conclusion=conclusion,
        valuation_view="undervalued",
        evidence_ids=evidence_ids,
        result_hash=f"sha256:{review_id}",
        created_at=DECISION_AT,
    )


def _quant_result(
    security_id: str,
    *,
    score: float,
    screening_status: ScreeningStatus,
    review_required: bool = False,
    review_reasons: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
    target_weight: float | None = None,
) -> QuantResult:
    """Build one deterministic quant result for dashboard projection tests.

    Args:
        security_id: str: .
        score: float: .
        screening_status: ScreeningStatus: .
        review_required: bool: .
        review_reasons: tuple[str, ...]: .
        risk_flags: tuple[str, ...]: .
        target_weight: float | None: .

    Returns:
        QuantResult: .
    """
    return QuantResult(
        quant_run_id="quant-1",
        security_id=security_id,
        final_score=score,
        quality_score=score,
        value_score=score,
        growth_score=score,
        momentum_score=score,
        risk_score=score,
        screening_status=screening_status,
        data_status=DataStatus.OK,
        review_required=review_required,
        review_reasons=review_reasons,
        risk_flags=risk_flags,
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary=f"{security_id} score {score}",
        factor_details=(
            {
                "strategy_family": "ml_lgbm_lifecycle",
                "ml_strategy": {"target_weight": target_weight},
            }
            if target_weight is not None
            else {}
        ),
        created_at=DECISION_AT,
    )
