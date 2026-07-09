"""Valuation discovery and quant query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.research.db_models import ResearchDeltaReviewRow
from margin.valuation_discovery.db_models import (
    AnalysisEvidenceLinkRow,
    AnalysisFindingRow,
    AnalysisMetricRow,
    AnalysisSnapshotRow,
    EffectiveAssessmentPointerRow,
    QuantFeatureRowRow,
    QuantFeatureSnapshotRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
    ResearchContextSnapshotRow,
    ValuationAssessmentEvidenceRow,
    ValuationAssessmentRow,
)


def quant_input_snapshots_ordered() -> Select:
    """Return all quant input snapshot rows ordered by creation time.

    Returns:
        Select: .
    """
    return select(QuantInputSnapshotRow).order_by(QuantInputSnapshotRow.created_at)


def all_quant_input_snapshot_facts() -> Select:
    """Return all quant input snapshot fact rows.

    Returns:
        Select: .
    """
    return select(QuantInputSnapshotFactRow)


def quant_input_snapshot_facts(snapshot_id: str) -> Select:
    """Return fact rows for one quant input snapshot ordered by fact_ref_id.

    Args:
        snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(QuantInputSnapshotFactRow)
        .where(QuantInputSnapshotFactRow.snapshot_id == snapshot_id)
        .order_by(QuantInputSnapshotFactRow.fact_ref_id)
    )


def latest_quant_feature_snapshot(
    *,
    scope_version_id: str,
    as_of,
) -> Select:
    """Return the latest QuantFeatureMart snapshot visible as of a time.

    Args:
        scope_version_id: str: .
        as_of: Any: .

    Returns:
        Select: .
    """
    return (
        select(QuantFeatureSnapshotRow)
        .where(
            QuantFeatureSnapshotRow.scope_version_id == scope_version_id,
            QuantFeatureSnapshotRow.decision_at <= as_of,
        )
        .order_by(
            QuantFeatureSnapshotRow.decision_at.desc(),
            QuantFeatureSnapshotRow.created_at.desc(),
            QuantFeatureSnapshotRow.feature_snapshot_id.desc(),
        )
        .limit(1)
    )


def quant_feature_rows_by_snapshot(feature_snapshot_id: str) -> Select:
    """Return feature rows for one QuantFeatureMart snapshot.

    Args:
        feature_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(QuantFeatureRowRow)
        .where(QuantFeatureRowRow.feature_snapshot_id == feature_snapshot_id)
        .order_by(QuantFeatureRowRow.security_id, QuantFeatureRowRow.row_id)
    )


def effective_assessment_pointers_ordered() -> Select:
    """Return effective assessment pointer events ordered by creation time.

    Returns:
        Select: .
    """
    return select(EffectiveAssessmentPointerRow).order_by(
        EffectiveAssessmentPointerRow.created_at,
        EffectiveAssessmentPointerRow.pointer_id,
    )


def valuation_assessments_ordered() -> Select:
    """Return assessments ordered by decision time.

    Returns:
        Select: .
    """
    return select(ValuationAssessmentRow).order_by(
        ValuationAssessmentRow.decision_at,
        ValuationAssessmentRow.assessment_id,
    )


def valuation_assessment_evidence_by_assessment(assessment_id: str) -> Select:
    """Return evidence edges for one assessment.

    Args:
        assessment_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ValuationAssessmentEvidenceRow)
        .where(ValuationAssessmentEvidenceRow.assessment_id == assessment_id)
        .order_by(
            ValuationAssessmentEvidenceRow.evidence_id,
            ValuationAssessmentEvidenceRow.edge_id,
        )
    )


def effective_assessment_pointers_for_count(
    scope_version_id: str,
    as_of,
) -> Select:
    """Return effective assessment pointers visible as of a time for a scope.

    Args:
        scope_version_id: str: .
        as_of: Any: .

    Returns:
        Select: .
    """
    return select(EffectiveAssessmentPointerRow).where(
        EffectiveAssessmentPointerRow.scope_version_id == scope_version_id,
        EffectiveAssessmentPointerRow.effective_from <= as_of,
    )


def latest_effective_pointer(
    security_id: str,
    scope_version_id: str,
) -> Select:
    """Load the latest effective assessment pointer for a security and scope.

    Args:
        security_id: str: .
        scope_version_id: str: .

    Returns:
        Select: .
    """
    return (
        select(EffectiveAssessmentPointerRow)
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


def quant_input_snapshot_id_for_run(quant_run_id: str) -> Select:
    """Resolve the frozen input snapshot ID behind one quant run.

    Args:
        quant_run_id: str: .

    Returns:
        Select: .
    """
    return select(QuantScreenRunRow.input_snapshot_id).where(
        QuantScreenRunRow.quant_run_id == quant_run_id
    )


def quant_news_candidate_results(
    quant_run_id: str,
    *,
    include_near_threshold: bool = False,
    scope_version_id: str | None = None,
) -> Select:
    """Return quant results eligible for agentic news acquisition.

    Args:
        quant_run_id: str: .
        include_near_threshold: bool: .
        scope_version_id: str | None: .

    Returns:
        Select: .
    """
    statuses = ["pass"]
    if include_near_threshold:
        statuses.append("near_threshold")
    statement = (
        select(QuantScreenResultRow)
        .join(
            QuantScreenRunRow,
            QuantScreenRunRow.quant_run_id == QuantScreenResultRow.quant_run_id,
        )
        .where(
            QuantScreenResultRow.quant_run_id == quant_run_id,
            QuantScreenResultRow.screening_status.in_(statuses),
        )
    )
    if scope_version_id is not None:
        statement = statement.where(QuantScreenRunRow.scope_version_id == scope_version_id)
    return statement.order_by(
        QuantScreenResultRow.screening_status.desc(),
        QuantScreenResultRow.security_id.asc(),
    )


def previous_quant_result(
    security_id: str,
    scope_version_id: str,
    current_quant_run_id: str,
) -> Select:
    """Load the immediately preceding quant result for delta routing.

    Args:
        security_id: str: .
        scope_version_id: str: .
        current_quant_run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(QuantScreenResultRow)
        .join(
            QuantScreenRunRow,
            QuantScreenRunRow.quant_run_id == QuantScreenResultRow.quant_run_id,
        )
        .where(
            QuantScreenResultRow.security_id == security_id,
            QuantScreenRunRow.scope_version_id == scope_version_id,
            QuantScreenResultRow.quant_run_id != current_quant_run_id,
        )
        .order_by(
            QuantScreenRunRow.decision_at.desc(),
            QuantScreenResultRow.created_at.desc(),
        )
        .limit(1)
    )


def context_snapshots_by_scope(scope_version_id: str) -> Select:
    """Return context snapshots for a scope ordered by security and ID.

    Args:
        scope_version_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchContextSnapshotRow)
        .where(ResearchContextSnapshotRow.scope_version_id == scope_version_id)
        .order_by(
            ResearchContextSnapshotRow.security_id,
            ResearchContextSnapshotRow.context_snapshot_id,
        )
    )


def latest_delta_review_id_for_context(context_snapshot_id: str) -> Select:
    """Return a persisted terminal review ID for one context.

    Args:
        context_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchDeltaReviewRow.review_id)
        .where(ResearchDeltaReviewRow.context_snapshot_id == context_snapshot_id)
        .order_by(ResearchDeltaReviewRow.created_at.desc())
        .limit(1)
    )


def latest_analysis_snapshot(
    *,
    security_id: str,
    scope_version_id: str | None = None,
    as_of,
) -> Select:
    """Return the latest Analysis Mart snapshot visible as of a time.

    Args:
        security_id: str: .
        scope_version_id: str | None: .
        as_of: Any: .

    Returns:
        Select: .
    """
    conditions = [
        AnalysisSnapshotRow.security_id == security_id,
        AnalysisSnapshotRow.decision_at <= as_of,
    ]
    if scope_version_id is not None:
        conditions.append(AnalysisSnapshotRow.scope_version_id == scope_version_id)
    return (
        select(AnalysisSnapshotRow)
        .where(*conditions)
        .order_by(
            AnalysisSnapshotRow.decision_at.desc(),
            AnalysisSnapshotRow.created_at.desc(),
            AnalysisSnapshotRow.analysis_snapshot_id.desc(),
        )
        .limit(1)
    )


def analysis_metrics_by_snapshot(analysis_snapshot_id: str) -> Select:
    """Return Analysis Mart metrics for one snapshot.

    Args:
        analysis_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(AnalysisMetricRow)
        .where(AnalysisMetricRow.analysis_snapshot_id == analysis_snapshot_id)
        .order_by(AnalysisMetricRow.metric_id)
    )


def analysis_findings_by_snapshot(analysis_snapshot_id: str) -> Select:
    """Return Analysis Mart findings for one snapshot.

    Args:
        analysis_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(AnalysisFindingRow)
        .where(AnalysisFindingRow.analysis_snapshot_id == analysis_snapshot_id)
        .order_by(AnalysisFindingRow.finding_id)
    )


def analysis_evidence_links_by_snapshot(analysis_snapshot_id: str) -> Select:
    """Return Analysis Mart evidence and lineage links for one snapshot.

    Args:
        analysis_snapshot_id: str: .

    Returns:
        Select: .
    """
    return (
        select(AnalysisEvidenceLinkRow)
        .where(AnalysisEvidenceLinkRow.analysis_snapshot_id == analysis_snapshot_id)
        .order_by(AnalysisEvidenceLinkRow.link_id)
    )
