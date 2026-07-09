"""Dashboard query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.dashboard.db_models import (
    DashboardFeedbackRow,
    DashboardItemRow,
    DashboardRunRow,
)
from margin.news.db_models import DocumentEventRow
from margin.research.db_models import ResearchDeltaReviewRow
from margin.valuation_discovery.db_models import (
    EffectiveAssessmentPointerRow,
    ResearchContextSnapshotRow,
    ValuationAssessmentRow,
)


def dashboard_runs(
    strategy_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Select:
    """Return dashboard runs sorted newest first with optional filters.

    Args:
        strategy_id: str | None: .
        status: str | None: .
        limit: int: .

    Returns:
        Select: .
    """
    statement = select(DashboardRunRow)
    if strategy_id:
        statement = statement.where(DashboardRunRow.strategy_id == strategy_id)
    if status:
        statement = statement.where(DashboardRunRow.status == status)
    return statement.order_by(DashboardRunRow.created_at.desc()).limit(limit)


def dashboard_items_by_run(run_id: str) -> Select:
    """Return all items for a run ordered by created_at.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(DashboardItemRow)
        .where(DashboardItemRow.run_id == run_id)
        .order_by(DashboardItemRow.created_at)
    )


def dashboard_feedback_by_item(item_id: str) -> Select:
    """Return feedback for one item ordered by created_at.

    Args:
        item_id: str: .

    Returns:
        Select: .
    """
    return (
        select(DashboardFeedbackRow)
        .where(DashboardFeedbackRow.item_id == item_id)
        .order_by(DashboardFeedbackRow.created_at)
    )


def dashboard_runs_by_scope(scope_version_id: str) -> Select:
    """Return dashboard runs for a scope version.

    Args:
        scope_version_id: str: .

    Returns:
        Select: .
    """
    return (
        select(DashboardRunRow)
        .where(DashboardRunRow.version_id == scope_version_id)
        .order_by(
            DashboardRunRow.decision_at.desc(),
            DashboardRunRow.created_at.desc(),
            DashboardRunRow.item_count.desc(),
            DashboardRunRow.run_id.desc(),
        )
    )


def dashboard_items_by_run_ids(run_ids: tuple[str, ...]) -> Select:
    """Return dashboard items for a set of run IDs.

    Args:
        run_ids: tuple[str, ...]: .

    Returns:
        Select: .
    """
    return select(DashboardItemRow).where(DashboardItemRow.run_id.in_(run_ids))


def latest_dashboard_research_context(
    *,
    security_id: str,
    scope_version_id: str,
    quant_run_id: str,
) -> Select:
    """Return the latest research context for one dashboard item.

    Args:
        security_id: str: .
        scope_version_id: str: .
        quant_run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchContextSnapshotRow)
        .where(
            ResearchContextSnapshotRow.security_id == security_id,
            ResearchContextSnapshotRow.scope_version_id == scope_version_id,
            ResearchContextSnapshotRow.payload_json["quant_run_id"].as_string() == quant_run_id,
        )
        .order_by(
            ResearchContextSnapshotRow.decision_at.desc(),
            ResearchContextSnapshotRow.created_at.desc(),
        )
        .limit(1)
    )


def latest_dashboard_delta_review(context_snapshot_id: str) -> Select:
    """Return the latest AI delta review for one research context snapshot.

    Args:
        context_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchDeltaReviewRow)
        .where(ResearchDeltaReviewRow.context_snapshot_id == context_snapshot_id)
        .order_by(ResearchDeltaReviewRow.created_at.desc())
        .limit(1)
    )


def dashboard_effective_assessment(
    *,
    security_id: str,
    scope_version_id: str,
) -> Select:
    """Return the current effective valuation assessment for one security.

    Args:
        security_id: str: .
        scope_version_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ValuationAssessmentRow)
        .join(
            EffectiveAssessmentPointerRow,
            ValuationAssessmentRow.assessment_id
            == EffectiveAssessmentPointerRow.effective_assessment_id,
        )
        .where(
            EffectiveAssessmentPointerRow.security_id == security_id,
            EffectiveAssessmentPointerRow.scope_version_id == scope_version_id,
        )
        .order_by(
            EffectiveAssessmentPointerRow.effective_from.desc(),
            EffectiveAssessmentPointerRow.created_at.desc(),
        )
        .limit(1)
    )


def dashboard_document_events(event_ids: tuple[str, ...]) -> Select:
    """Return document events referenced by a dashboard research context.

    Args:
        event_ids: tuple[str, ...]: .

    Returns:
        Select: .
    """
    return (
        select(DocumentEventRow)
        .where(DocumentEventRow.event_id.in_(event_ids))
        .order_by(DocumentEventRow.published_at.desc(), DocumentEventRow.event_id.desc())
    )
