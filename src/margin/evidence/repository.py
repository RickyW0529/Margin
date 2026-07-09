"""PostgreSQL repository for immutable RAG evidence, claims, and audits."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from margin.evidence.db_models import (
    ClaimEvidenceLinkRow,
    EvidenceClaimRow,
    EvidenceConflictRow,
    EvidencePackageItemRow,
    EvidencePackageRow,
    EvidenceRecordRow,
    EvidenceValidationAuditRow,
    NewsContextEvidenceRow,
    ResearchEvidenceRow,
)
from margin.evidence.models import (
    Claim,
    ClaimEvidenceLink,
    ClaimEvidenceRole,
    ClaimStatus,
    ClaimType,
    ConflictRecord,
    ConflictSeverity,
    Evidence,
    EvidenceConflict,
    EvidencePackage,
    EvidencePackageQualityStatus,
    FactOrInference,
)
from margin.evidence.validator import (
    FailReason,
    ValidationAuditRecord,
    ValidationStatus,
)
from margin.news.models import SourceLevel, utc_now
from margin.sql.evidence_queries import (
    claim_evidence_by_claim,
    evidence_conflicts_by_package,
    evidence_package_latest_version,
    evidence_package_root_for_update,
    evidence_records_by_ids,
    news_context_evidence_by_bundle,
    research_evidence_by_item,
    validation_audits_by_claim,
)


class ResearchEvidenceLink(BaseModel):
    """Persisted link between a research item, a claim, and an evidence record.."""

    research_item_id: str
    claim_id: str
    evidence_id: str
    role: str
    rank: int
    created_at: datetime

    model_config = {"frozen": True}


class NewsContextEvidenceLink(BaseModel):
    """Persisted link between a news context bundle and evidence.."""

    bundle_id: str
    evidence_id: str
    created_at: datetime

    model_config = {"frozen": True}


class EvidenceRepository:
    """SQLAlchemy-backed append-only persistence boundary for module 05.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def add_evidence(self, evidence: Evidence) -> None:
        """Persist an evidence record idempotently, rejecting mutation attempts.

        Args:
            evidence: Evidence: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(EvidenceRecordRow, evidence.evidence_id)
            if row is None:
                session.add(_evidence_to_row(evidence))
                return
            if _evidence_from_row(row) != evidence:
                raise ValueError(f"evidence '{evidence.evidence_id}' is immutable")

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Fetch an evidence record by ID.

        Args:
            evidence_id: str: .

        Returns:
            Evidence | None: .
        """
        with self._session_factory() as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            return _evidence_from_row(row) if row is not None else None

    def add_claim(self, claim: Claim) -> None:
        """Persist a claim idempotently, rejecting mutation attempts.

        Args:
            claim: Claim: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(EvidenceClaimRow, claim.claim_id)
            if row is None:
                session.add(_claim_to_row(claim))
                return
            if _claim_from_row(row) != claim:
                raise ValueError(f"claim '{claim.claim_id}' is immutable")

    def get_claim(self, claim_id: str) -> Claim | None:
        """Fetch a persisted claim by ID.

        Args:
            claim_id: str: .

        Returns:
            Claim | None: .
        """
        with self._session_factory() as session:
            row = session.get(EvidenceClaimRow, claim_id)
            return _claim_from_row(row) if row is not None else None

    def add_validation_audit(self, audit: ValidationAuditRecord) -> None:
        """Append a validation audit record, rejecting mutation of existing rows.

        Args:
            audit: ValidationAuditRecord: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(EvidenceValidationAuditRow, audit.audit_id)
            if row is None:
                session.add(_audit_to_row(audit))
                return
            if _audit_from_row(row) != audit:
                raise ValueError(f"audit '{audit.audit_id}' is immutable")

    def list_validation_audits(self, claim_id: str) -> list[ValidationAuditRecord]:
        """List validation audits for a claim in chronological order.

        Args:
            claim_id: str: .

        Returns:
            list[ValidationAuditRecord]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(validation_audits_by_claim(claim_id)).all()
            return [_audit_from_row(row) for row in rows]

    def link_research_evidence(
        self,
        *,
        research_item_id: str,
        claim_id: str,
        evidence_id: str,
        role: str,
        rank: int,
    ) -> None:
        """Persist a research-item evidence link idempotently.

        Args:
            research_item_id: str: .
            claim_id: str: .
            evidence_id: str: .
            role: str: .
            rank: int: .

        Returns:
            None: .
        """
        key = (research_item_id, claim_id, evidence_id, role)
        with self._session_factory.begin() as session:
            row = session.get(ResearchEvidenceRow, key)
            if row is None:
                session.add(
                    ResearchEvidenceRow(
                        research_item_id=research_item_id,
                        claim_id=claim_id,
                        evidence_id=evidence_id,
                        role=role,
                        rank=rank,
                        created_at=utc_now(),
                    )
                )
                return
            if row.rank != rank:
                raise ValueError(
                    "research evidence link is immutable: "
                    f"{research_item_id}/{claim_id}/{evidence_id}/{role}"
                )

    def list_research_evidence(self, research_item_id: str) -> list[ResearchEvidenceLink]:
        """List evidence links for a research item ordered by rank.

        Args:
            research_item_id: str: .

        Returns:
            list[ResearchEvidenceLink]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(research_evidence_by_item(research_item_id)).all()
            return [_research_evidence_from_row(row) for row in rows]

    def add_evidence_package(self, package: EvidencePackage) -> None:
        """Persist a frozen evidence package version append-only.

        Args:
            package: EvidencePackage: .

        Returns:
            None: .
        """
        key = (package.package_id, package.version)
        with self._session_factory.begin() as session:
            row = session.get(EvidencePackageRow, key)
            if row is None:
                session.add(_package_to_row(package))
                session.flush()
                for item in _package_item_rows(package):
                    session.add(item)
                return
            if _package_from_row(row) != package:
                raise ValueError(
                    f"evidence package '{package.package_id}/{package.version}' is immutable"
                )

    def get_evidence_package(
        self,
        package_id: str,
        version: int,
    ) -> EvidencePackage | None:
        """Fetch a frozen evidence package version by composite key.

        Args:
            package_id: str: .
            version: int: .

        Returns:
            EvidencePackage | None: .
        """
        with self._session_factory() as session:
            row = session.get(EvidencePackageRow, (package_id, version))
            return _package_from_row(row) if row is not None else None

    def create_package_revision(
        self,
        parent_package_id: str,
        added_evidence_ids: tuple[str, ...],
        *,
        retrieval_audit_id: str | None = None,
        coverage: float | None = None,
        quality_status: EvidencePackageQualityStatus | None = None,
    ) -> EvidencePackage:
        """Create the next immutable version of an evidence package.

        Args:
            parent_package_id: str: .
            added_evidence_ids: tuple[str, ...]: .
            retrieval_audit_id: str | None: .
            coverage: float | None: .
            quality_status: EvidencePackageQualityStatus | None: .

        Returns:
            EvidencePackage: .
        """
        requested_ids = tuple(dict.fromkeys(added_evidence_ids))
        if not requested_ids:
            raise ValueError("package revision requires at least one evidence ID")

        with self._session_factory.begin() as session:
            root_row = session.scalar(evidence_package_root_for_update(parent_package_id))
            if root_row is None:
                raise KeyError(f"evidence package '{parent_package_id}' not found")

            parent_row = session.scalar(evidence_package_latest_version(parent_package_id))
            assert parent_row is not None
            parent = _package_from_row(parent_row)

            new_ids = tuple(
                evidence_id
                for evidence_id in requested_ids
                if evidence_id not in parent.evidence_ids
            )
            if not new_ids:
                raise ValueError("package revision contains no new evidence IDs")

            evidence_rows = {
                row.evidence_id: row
                for row in session.scalars(evidence_records_by_ids(new_ids)).all()
            }
            missing_ids = [
                evidence_id for evidence_id in new_ids if evidence_id not in evidence_rows
            ]
            if missing_ids:
                raise KeyError(
                    "package revision references unknown evidence IDs: " + ",".join(missing_ids)
                )

            merged_max_available_at = max(
                (
                    timestamp
                    for timestamp in (
                        parent.max_available_at,
                        *(evidence_rows[evidence_id].available_at for evidence_id in new_ids),
                    )
                    if timestamp is not None
                ),
                default=None,
            )
            revision = parent.model_copy(
                update={
                    "version": parent.version + 1,
                    "evidence_ids": parent.evidence_ids + new_ids,
                    "coverage": parent.coverage if coverage is None else coverage,
                    "quality_status": (
                        parent.quality_status if quality_status is None else quality_status
                    ),
                    "max_available_at": merged_max_available_at,
                    "retrieval_audit_id": (
                        retrieval_audit_id
                        if retrieval_audit_id is not None
                        else parent.retrieval_audit_id
                    ),
                    "parent_package_id": parent.package_id,
                    "added_evidence_ids": new_ids,
                }
            )
            session.add(_package_to_row(revision))
            session.flush()
            session.add_all(_package_item_rows(revision))
            return revision

    def link_news_context_evidence(self, bundle_id: str, evidence_id: str) -> None:
        """Persist an immutable news-context to evidence link idempotently.

        Args:
            bundle_id: str: .
            evidence_id: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsContextEvidenceRow, (bundle_id, evidence_id))
            if row is None:
                session.add(
                    NewsContextEvidenceRow(
                        bundle_id=bundle_id,
                        evidence_id=evidence_id,
                        created_at=utc_now(),
                    )
                )

    def list_news_context_evidence(
        self,
        bundle_id: str,
    ) -> list[NewsContextEvidenceLink]:
        """List evidence links for a news context bundle.

        Args:
            bundle_id: str: .

        Returns:
            list[NewsContextEvidenceLink]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_context_evidence_by_bundle(bundle_id)).all()
            return [_news_context_evidence_from_row(row) for row in rows]

    def link_claim_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        *,
        role: ClaimEvidenceRole,
        rank: int = 0,
    ) -> None:
        """Persist an immutable claim-evidence role link idempotently.

        Args:
            claim_id: str: .
            evidence_id: str: .
            role: ClaimEvidenceRole: .
            rank: int: .

        Returns:
            None: .
        """
        role_value = role.value if isinstance(role, ClaimEvidenceRole) else str(role)
        key = (claim_id, evidence_id, role_value)
        with self._session_factory.begin() as session:
            row = session.get(ClaimEvidenceLinkRow, key)
            if row is None:
                session.add(
                    ClaimEvidenceLinkRow(
                        claim_id=claim_id,
                        evidence_id=evidence_id,
                        role=role_value,
                        rank=rank,
                        created_at=utc_now(),
                    )
                )
                return
            if row.rank != rank:
                raise ValueError(
                    f"claim evidence link is immutable: {claim_id}/{evidence_id}/{role_value}"
                )

    def list_claim_evidence(self, claim_id: str) -> list[ClaimEvidenceLink]:
        """List claim-evidence role links ordered by rank.

        Args:
            claim_id: str: .

        Returns:
            list[ClaimEvidenceLink]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(claim_evidence_by_claim(claim_id)).all()
            return [_claim_evidence_link_from_row(row) for row in rows]

    def add_evidence_conflict(self, conflict: EvidenceConflict) -> None:
        """Persist an immutable evidence conflict.

        Args:
            conflict: EvidenceConflict: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(EvidenceConflictRow, conflict.conflict_id)
            if row is None:
                session.add(_evidence_conflict_to_row(conflict))
                return
            if _evidence_conflict_from_row(row) != conflict:
                raise ValueError(f"evidence conflict '{conflict.conflict_id}' is immutable")

    def list_evidence_conflicts(
        self,
        package_id: str,
        version: int,
    ) -> list[EvidenceConflict]:
        """List conflicts recorded for an evidence package version.

        Args:
            package_id: str: .
            version: int: .

        Returns:
            list[EvidenceConflict]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(evidence_conflicts_by_package(package_id, version)).all()
            return [_evidence_conflict_from_row(row) for row in rows]


def _evidence_to_row(evidence: Evidence) -> EvidenceRecordRow:
    """Convert an Evidence domain model to a database row.

    Args:
        evidence: Evidence: .

    Returns:
        EvidenceRecordRow: .
    """
    return EvidenceRecordRow(
        evidence_id=evidence.evidence_id,
        chunk_id=evidence.chunk_id,
        document_id=evidence.document_id,
        source_type=evidence.source_type,
        source_url=evidence.source_url,
        source_name=evidence.source_name,
        source_level=int(evidence.source_level),
        quality_score=evidence.quality_score,
        content_hash=evidence.content_hash,
        content=evidence.content,
        symbol=evidence.symbol,
        published_at=evidence.published_at,
        available_at=evidence.available_at,
        retrieved_at=evidence.retrieved_at,
        page=evidence.page,
        bbox=list(evidence.bbox) if evidence.bbox else None,
        section=evidence.section,
        paragraph_index=evidence.paragraph_index,
        dom_path=evidence.dom_path,
        table_id=evidence.table_id,
        row_id=evidence.row_id,
        column_id=evidence.column_id,
        quote_span=list(evidence.quote_span) if evidence.quote_span else None,
        snapshot_id=evidence.snapshot_id,
        snapshot_hash=evidence.snapshot_hash,
        created_at=utc_now(),
    )


def _evidence_from_row(row: EvidenceRecordRow) -> Evidence:
    """Convert an EvidenceRecordRow to an Evidence domain model.

    Args:
        row: EvidenceRecordRow: .

    Returns:
        Evidence: .
    """
    return Evidence(
        evidence_id=row.evidence_id,
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        source_type=row.source_type,
        source_url=row.source_url,
        source_name=row.source_name,
        source_level=SourceLevel(row.source_level),
        quality_score=row.quality_score,
        content_hash=row.content_hash,
        content=row.content,
        symbol=row.symbol,
        published_at=row.published_at,
        available_at=row.available_at,
        retrieved_at=row.retrieved_at,
        page=row.page,
        bbox=tuple(row.bbox) if row.bbox else None,
        section=row.section,
        paragraph_index=row.paragraph_index,
        dom_path=row.dom_path,
        table_id=row.table_id,
        row_id=row.row_id,
        column_id=row.column_id,
        quote_span=tuple(row.quote_span) if row.quote_span else None,
        snapshot_id=row.snapshot_id,
        snapshot_hash=row.snapshot_hash,
    )


def _claim_to_row(claim: Claim) -> EvidenceClaimRow:
    """Convert a Claim domain model to a database row.

    Args:
        claim: Claim: .

    Returns:
        EvidenceClaimRow: .
    """
    return EvidenceClaimRow(
        claim_id=claim.claim_id,
        claim_type=claim.claim_type.value,
        statement=claim.statement,
        status=claim.status.value,
        fact_or_inference=claim.fact_or_inference.value,
        evidence_ids=list(claim.evidence_ids),
        confidence=claim.confidence,
        conflicts=[conflict.model_dump(mode="json") for conflict in claim.conflicts],
        effective_at=claim.effective_at,
        locator=claim.locator,
        symbol=claim.symbol,
        created_at=utc_now(),
    )


def _claim_from_row(row: EvidenceClaimRow) -> Claim:
    """Convert an EvidenceClaimRow to a Claim domain model.

    Args:
        row: EvidenceClaimRow: .

    Returns:
        Claim: .
    """
    return Claim(
        claim_id=row.claim_id,
        claim_type=ClaimType(row.claim_type),
        statement=row.statement,
        status=ClaimStatus(row.status),
        fact_or_inference=FactOrInference(row.fact_or_inference),
        evidence_ids=list(row.evidence_ids),
        confidence=row.confidence,
        conflicts=[ConflictRecord(**item) for item in row.conflicts],
        effective_at=row.effective_at,
        locator=row.locator,
        symbol=row.symbol,
    )


def _audit_to_row(audit: ValidationAuditRecord) -> EvidenceValidationAuditRow:
    """Convert a ValidationAuditRecord domain model to a database row.

    Args:
        audit: ValidationAuditRecord: .

    Returns:
        EvidenceValidationAuditRow: .
    """
    return EvidenceValidationAuditRow(
        audit_id=audit.audit_id,
        claim_id=audit.claim_id,
        status=audit.status.value,
        reason=audit.reason,
        fail_reason=audit.fail_reason.value if audit.fail_reason else None,
        original_confidence=audit.original_confidence,
        capped_confidence=audit.capped_confidence,
        conflicts_found=audit.conflicts_found,
        evidences_checked=audit.evidences_checked,
        evidences_passed=audit.evidences_passed,
        requires_counter_review=audit.requires_counter_review,
        checked_at=audit.checked_at,
        created_at=utc_now(),
    )


def _audit_from_row(row: EvidenceValidationAuditRow) -> ValidationAuditRecord:
    """Convert an EvidenceValidationAuditRow to a ValidationAuditRecord model.

    Args:
        row: EvidenceValidationAuditRow: .

    Returns:
        ValidationAuditRecord: .
    """
    return ValidationAuditRecord(
        audit_id=row.audit_id,
        claim_id=row.claim_id,
        status=ValidationStatus(row.status),
        reason=row.reason,
        fail_reason=FailReason(row.fail_reason) if row.fail_reason else None,
        original_confidence=row.original_confidence,
        capped_confidence=row.capped_confidence,
        conflicts_found=row.conflicts_found,
        evidences_checked=row.evidences_checked,
        evidences_passed=row.evidences_passed,
        requires_counter_review=row.requires_counter_review,
        checked_at=row.checked_at,
    )


def _research_evidence_from_row(row: ResearchEvidenceRow) -> ResearchEvidenceLink:
    """Convert a ResearchEvidenceRow to a ResearchEvidenceLink model.

    Args:
        row: ResearchEvidenceRow: .

    Returns:
        ResearchEvidenceLink: .
    """
    return ResearchEvidenceLink(
        research_item_id=row.research_item_id,
        claim_id=row.claim_id,
        evidence_id=row.evidence_id,
        role=row.role,
        rank=row.rank,
        created_at=row.created_at,
    )


def _package_to_row(package: EvidencePackage) -> EvidencePackageRow:
    """Convert an EvidencePackage model to a database row.

    Args:
        package: EvidencePackage: .

    Returns:
        EvidencePackageRow: .
    """
    return EvidencePackageRow(
        package_id=package.package_id,
        version=package.version,
        security_id=package.security_id,
        decision_at=package.decision_at,
        scope_hash=package.scope_hash,
        questions=list(package.questions),
        evidence_ids=list(package.evidence_ids),
        claim_ids=list(package.claim_ids),
        conflict_ids=list(package.conflict_ids),
        coverage=package.coverage,
        quality_status=package.quality_status.value,
        max_available_at=package.max_available_at,
        retrieval_audit_id=package.retrieval_audit_id,
        parent_package_id=package.parent_package_id,
        added_evidence_ids=list(package.added_evidence_ids),
        created_at=utc_now(),
    )


def _package_from_row(row: EvidencePackageRow) -> EvidencePackage:
    """Convert an EvidencePackageRow to an EvidencePackage model.

    Args:
        row: EvidencePackageRow: .

    Returns:
        EvidencePackage: .
    """
    return EvidencePackage(
        package_id=row.package_id,
        version=row.version,
        security_id=row.security_id,
        decision_at=row.decision_at,
        scope_hash=row.scope_hash,
        questions=tuple(row.questions),
        evidence_ids=tuple(row.evidence_ids),
        claim_ids=tuple(row.claim_ids),
        conflict_ids=tuple(row.conflict_ids),
        coverage=row.coverage,
        quality_status=EvidencePackageQualityStatus(row.quality_status),
        max_available_at=row.max_available_at,
        retrieval_audit_id=row.retrieval_audit_id,
        parent_package_id=row.parent_package_id,
        added_evidence_ids=tuple(row.added_evidence_ids),
    )


def _package_item_rows(package: EvidencePackage) -> list[EvidencePackageItemRow]:
    """Materialize package membership rows for package replay and search.

    Args:
        package: EvidencePackage: .

    Returns:
        list[EvidencePackageItemRow]: .
    """
    rows: list[EvidencePackageItemRow] = []
    for item_type, item_ids in (
        ("evidence", package.evidence_ids),
        ("claim", package.claim_ids),
        ("conflict", package.conflict_ids),
    ):
        rows.extend(
            EvidencePackageItemRow(
                package_id=package.package_id,
                version=package.version,
                item_type=item_type,
                item_id=item_id,
                rank=index + 1,
                created_at=utc_now(),
            )
            for index, item_id in enumerate(item_ids)
        )
    return rows


def _news_context_evidence_from_row(
    row: NewsContextEvidenceRow,
) -> NewsContextEvidenceLink:
    """Convert a NewsContextEvidenceRow to a domain link.

    Args:
        row: NewsContextEvidenceRow: .

    Returns:
        NewsContextEvidenceLink: .
    """
    return NewsContextEvidenceLink(
        bundle_id=row.bundle_id,
        evidence_id=row.evidence_id,
        created_at=row.created_at,
    )


def _claim_evidence_link_from_row(row: ClaimEvidenceLinkRow) -> ClaimEvidenceLink:
    """Convert a ClaimEvidenceLinkRow to a domain link.

    Args:
        row: ClaimEvidenceLinkRow: .

    Returns:
        ClaimEvidenceLink: .
    """
    return ClaimEvidenceLink(
        claim_id=row.claim_id,
        evidence_id=row.evidence_id,
        role=ClaimEvidenceRole(row.role),
        rank=row.rank,
        created_at=row.created_at,
    )


def _evidence_conflict_to_row(conflict: EvidenceConflict) -> EvidenceConflictRow:
    """Convert an EvidenceConflict domain model to a database row.

    Args:
        conflict: EvidenceConflict: .

    Returns:
        EvidenceConflictRow: .
    """
    return EvidenceConflictRow(
        conflict_id=conflict.conflict_id,
        package_id=conflict.package_id,
        version=conflict.version,
        security_id=conflict.security_id,
        evidence_id=conflict.evidence_id,
        conflicting_evidence_id=conflict.conflicting_evidence_id,
        reason=conflict.reason,
        severity=conflict.severity.value,
        created_at=conflict.created_at,
    )


def _evidence_conflict_from_row(row: EvidenceConflictRow) -> EvidenceConflict:
    """Convert an EvidenceConflictRow to a domain model.

    Args:
        row: EvidenceConflictRow: .

    Returns:
        EvidenceConflict: .
    """
    return EvidenceConflict(
        conflict_id=row.conflict_id,
        package_id=row.package_id,
        version=row.version,
        security_id=row.security_id,
        evidence_id=row.evidence_id,
        conflicting_evidence_id=row.conflicting_evidence_id,
        reason=row.reason,
        severity=ConflictSeverity(row.severity),
        created_at=row.created_at,
    )
