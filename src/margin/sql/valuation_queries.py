"""Valuation discovery and quant query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.research.db_models import ResearchDeltaReviewRow
from margin.valuation_discovery.db_models import (
    EffectiveAssessmentPointerRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
    ResearchContextSnapshotRow,
    ValuationAssessmentEvidenceRow,
    ValuationAssessmentRow,
)


def quant_input_snapshots_ordered() -> Select:
    """Return all quant input snapshot rows ordered by creation time."""
    return select(QuantInputSnapshotRow).order_by(QuantInputSnapshotRow.created_at)


def all_quant_input_snapshot_facts() -> Select:
    """Return all quant input snapshot fact rows."""
    return select(QuantInputSnapshotFactRow)


def quant_input_snapshot_facts(snapshot_id: str) -> Select:
    """Return fact rows for one quant input snapshot ordered by fact_ref_id."""
    return (
        select(QuantInputSnapshotFactRow)
        .where(QuantInputSnapshotFactRow.snapshot_id == snapshot_id)
        .order_by(QuantInputSnapshotFactRow.fact_ref_id)
    )


def effective_assessment_pointers_ordered() -> Select:
    """Return effective assessment pointer events ordered by creation time."""
    return (
        select(EffectiveAssessmentPointerRow)
        .order_by(
            EffectiveAssessmentPointerRow.created_at,
            EffectiveAssessmentPointerRow.pointer_id,
        )
    )


def valuation_assessments_ordered() -> Select:
    """Return assessments ordered by decision time."""
    return (
        select(ValuationAssessmentRow)
        .order_by(
            ValuationAssessmentRow.decision_at,
            ValuationAssessmentRow.assessment_id,
        )
    )


def valuation_assessment_evidence_by_assessment(assessment_id: str) -> Select:
    """Return evidence edges for one assessment."""
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
    """Return effective assessment pointers visible as of a time for a scope."""
    return (
        select(EffectiveAssessmentPointerRow)
        .where(
            EffectiveAssessmentPointerRow.scope_version_id == scope_version_id,
            EffectiveAssessmentPointerRow.effective_from <= as_of,
        )
    )


def latest_effective_pointer(
    security_id: str,
    scope_version_id: str,
) -> Select:
    """Load the latest effective assessment pointer for a security and scope."""
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
    """Resolve the frozen input snapshot ID behind one quant run."""
    return select(QuantScreenRunRow.input_snapshot_id).where(
        QuantScreenRunRow.quant_run_id == quant_run_id
    )


def previous_quant_result(
    security_id: str,
    scope_version_id: str,
    current_quant_run_id: str,
) -> Select:
    """Load the immediately preceding quant result for delta routing."""
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
    """Return context snapshots for a scope ordered by security and ID."""
    return (
        select(ResearchContextSnapshotRow)
        .where(ResearchContextSnapshotRow.scope_version_id == scope_version_id)
        .order_by(
            ResearchContextSnapshotRow.security_id,
            ResearchContextSnapshotRow.context_snapshot_id,
        )
    )


def latest_delta_review_id_for_context(context_snapshot_id: str) -> Select:
    """Return a persisted terminal review ID for one context."""
    return (
        select(ResearchDeltaReviewRow.review_id)
        .where(ResearchDeltaReviewRow.context_snapshot_id == context_snapshot_id)
        .order_by(ResearchDeltaReviewRow.created_at.desc())
        .limit(1)
    )
