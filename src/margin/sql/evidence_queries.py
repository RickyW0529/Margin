"""Evidence and citation query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.evidence.db_models import (
    ClaimEvidenceLinkRow,
    EvidenceConflictRow,
    EvidencePackageRow,
    EvidenceRecordRow,
    EvidenceValidationAuditRow,
    NewsContextEvidenceRow,
    ResearchEvidenceRow,
)


def validation_audits_by_claim(claim_id: str) -> Select:
    """List validation audits for a claim in chronological order.

    Args:
        claim_id: str: .

    Returns:
        Select: .
    """
    return (
        select(EvidenceValidationAuditRow)
        .where(EvidenceValidationAuditRow.claim_id == claim_id)
        .order_by(
            EvidenceValidationAuditRow.checked_at,
            EvidenceValidationAuditRow.audit_id,
        )
    )


def research_evidence_by_item(research_item_id: str) -> Select:
    """List evidence links for a research item ordered by rank.

    Args:
        research_item_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchEvidenceRow)
        .where(ResearchEvidenceRow.research_item_id == research_item_id)
        .order_by(ResearchEvidenceRow.rank, ResearchEvidenceRow.created_at)
    )


def evidence_package_root_for_update(package_id: str) -> Select:
    """Lock the first version row of an evidence package for revision.

    Args:
        package_id: str: .

    Returns:
        Select: .
    """
    return (
        select(EvidencePackageRow)
        .where(EvidencePackageRow.package_id == package_id)
        .order_by(EvidencePackageRow.version)
        .limit(1)
        .with_for_update()
    )


def evidence_package_latest_version(package_id: str) -> Select:
    """Return the latest version row of an evidence package.

    Args:
        package_id: str: .

    Returns:
        Select: .
    """
    return (
        select(EvidencePackageRow)
        .where(EvidencePackageRow.package_id == package_id)
        .order_by(EvidencePackageRow.version.desc())
        .limit(1)
    )


def evidence_records_by_ids(evidence_ids: tuple[str, ...]) -> Select:
    """Return evidence records matching the given IDs.

    Args:
        evidence_ids: tuple[str, ...]: .

    Returns:
        Select: .
    """
    return select(EvidenceRecordRow).where(EvidenceRecordRow.evidence_id.in_(evidence_ids))


def news_context_evidence_by_bundle(bundle_id: str) -> Select:
    """List evidence links for a news context bundle.

    Args:
        bundle_id: str: .

    Returns:
        Select: .
    """
    return (
        select(NewsContextEvidenceRow)
        .where(NewsContextEvidenceRow.bundle_id == bundle_id)
        .order_by(
            NewsContextEvidenceRow.created_at,
            NewsContextEvidenceRow.evidence_id,
        )
    )


def claim_evidence_by_claim(claim_id: str) -> Select:
    """List claim-evidence role links ordered by rank.

    Args:
        claim_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ClaimEvidenceLinkRow)
        .where(ClaimEvidenceLinkRow.claim_id == claim_id)
        .order_by(ClaimEvidenceLinkRow.rank, ClaimEvidenceLinkRow.created_at)
    )


def evidence_conflicts_by_package(
    package_id: str,
    version: int,
) -> Select:
    """List conflicts recorded for an evidence package version.

    Args:
        package_id: str: .
        version: int: .

    Returns:
        Select: .
    """
    return (
        select(EvidenceConflictRow)
        .where(
            EvidenceConflictRow.package_id == package_id,
            EvidenceConflictRow.version == version,
        )
        .order_by(
            EvidenceConflictRow.created_at,
            EvidenceConflictRow.conflict_id,
        )
    )
