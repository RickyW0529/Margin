"""Production valuation publisher behavior tests.

This module validates that the valuation publisher adapter uses persisted AI
reviews without inventing identifiers, is replay-idempotent, handles
first-run abstention correctly, and refreshes the dashboard from persisted
pointers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from margin.dashboard.models import DashboardFilters, DashboardSort
from margin.dashboard.repository import MemoryDashboardRepository
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
    """Minimal persisted-review summary consumed by the publisher.

    Attributes:
        review_ids: Tuple of persisted review identifiers.
        context_snapshot_ids: Tuple of frozen context snapshot identifiers.
    """

    review_ids: tuple[str, ...]
    context_snapshot_ids: tuple[str, ...] = ()


def test_update_review_publishes_real_assessment_evidence_and_pointer() -> None:
    """Verify the publisher uses the persisted AI review without inventing identifiers.

    Returns:
        None.
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
        edge.evidence_id
        for edge in valuations.list_valuation_assessment_evidence(
            "assessment-new"
        )
    ] == ["evidence-1", "evidence-2"]
    [pointer] = valuations.list_effective_assessment_pointers()
    assert pointer.effective_assessment_id == "assessment-new"
    assert pointer.previous_assessment_id == "assessment-old"
    assert pointer.effective_from == DECISION_AT


def test_publisher_replay_is_idempotent() -> None:
    """Verify retrying the publication step does not duplicate immutable records.

    Returns:
        None.
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
    assert len(
        valuations.list_valuation_assessment_evidence("assessment-invalid")
    ) == 1


def test_abstain_without_previous_assessment_does_not_create_fake_pointer() -> None:
    """Verify a first-run abstention remains review-only until an assessment exists.

    Returns:
        None.
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
        None.
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
    """Verify refresh writes visible quant results into the dashboard repository."""
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
    assert response.items[1].screening_status == "near_threshold"
    assert response.items[1].review_required is True


def _review(
    *,
    review_id: str,
    outcome: ReviewOutcome,
    previous_assessment_id: str | None,
    effective_assessment_id: str | None,
    conclusion: str,
    evidence_ids: tuple[str, ...],
) -> ResearchDeltaReview:
    """Build one deterministic ResearchDeltaReview for publisher adapter tests."""

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
        stale_reason=(
            "insufficient_evidence"
            if outcome is ReviewOutcome.ABSTAIN
            else None
        ),
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
) -> QuantResult:
    """Build one deterministic quant result for dashboard projection tests."""
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
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary=f"{security_id} score {score}",
        created_at=DECISION_AT,
    )
