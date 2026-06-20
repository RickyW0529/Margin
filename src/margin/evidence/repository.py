"""PostgreSQL repository for immutable RAG evidence, claims, and audits."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.evidence.db_models import (
    EvidenceClaimRow,
    EvidenceRecordRow,
    EvidenceValidationAuditRow,
    ResearchEvidenceRow,
)
from margin.evidence.models import (
    Claim,
    ClaimType,
    ConflictRecord,
    Evidence,
    FactOrInference,
)
from margin.evidence.validator import (
    FailReason,
    ValidationAuditRecord,
    ValidationStatus,
)
from margin.news.models import SourceLevel, utc_now


class ResearchEvidenceLink(BaseModel):
    """Persisted link between a research item, a claim, and an evidence record.

    Attributes:
        research_item_id: Identifier of the research item.
        claim_id: Identifier of the linked claim.
        evidence_id: Identifier of the linked evidence record.
        role: Role of the evidence in the research item (e.g. "supporting").
        rank: Display order of the link.
        created_at: Timestamp when the link was created (UTC).
    """

    research_item_id: str
    claim_id: str
    evidence_id: str
    role: str
    rank: int
    created_at: datetime

    model_config = {"frozen": True}


class EvidenceRepository:
    """SQLAlchemy-backed append-only persistence boundary for module 05."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy Session.
        """
        self._session_factory = session_factory

    def add_evidence(self, evidence: Evidence) -> None:
        """Persist an evidence record idempotently, rejecting mutation attempts.

        Args:
            evidence: The evidence record to persist.

        Raises:
            ValueError: If a different evidence record with the same ID already
                exists.
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
            evidence_id: Unique identifier of the evidence record.

        Returns:
            The evidence record if found, otherwise None.
        """
        with self._session_factory() as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            return _evidence_from_row(row) if row is not None else None

    def add_claim(self, claim: Claim) -> None:
        """Persist a claim idempotently, rejecting mutation attempts.

        Args:
            claim: The claim to persist.

        Raises:
            ValueError: If a different claim with the same ID already exists.
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
            claim_id: Unique identifier of the claim.

        Returns:
            The claim if found, otherwise None.
        """
        with self._session_factory() as session:
            row = session.get(EvidenceClaimRow, claim_id)
            return _claim_from_row(row) if row is not None else None

    def add_validation_audit(self, audit: ValidationAuditRecord) -> None:
        """Append a validation audit record, rejecting mutation of existing rows.

        Args:
            audit: The validation audit record to persist.

        Raises:
            ValueError: If a different audit record with the same ID already
                exists.
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
            claim_id: Identifier of the claim whose audits are requested.

        Returns:
            List of validation audit records ordered by checked_at and audit_id.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(EvidenceValidationAuditRow)
                .where(EvidenceValidationAuditRow.claim_id == claim_id)
                .order_by(
                    EvidenceValidationAuditRow.checked_at,
                    EvidenceValidationAuditRow.audit_id,
                )
            ).all()
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
            research_item_id: Identifier of the research item.
            claim_id: Identifier of the linked claim.
            evidence_id: Identifier of the linked evidence record.
            role: Role of the evidence in the research item.
            rank: Display order of the link.

        Raises:
            ValueError: If an existing link with the same composite key has a
                different rank.
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
            research_item_id: Identifier of the research item.

        Returns:
            List of ResearchEvidenceLink records ordered by rank and created_at.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(ResearchEvidenceRow)
                .where(ResearchEvidenceRow.research_item_id == research_item_id)
                .order_by(ResearchEvidenceRow.rank, ResearchEvidenceRow.created_at)
            ).all()
            return [_research_evidence_from_row(row) for row in rows]


def _evidence_to_row(evidence: Evidence) -> EvidenceRecordRow:
    """Convert an Evidence domain model to a database row."""
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
        section=evidence.section,
        paragraph_index=evidence.paragraph_index,
        table_id=evidence.table_id,
        row_id=evidence.row_id,
        quote_span=list(evidence.quote_span) if evidence.quote_span else None,
        snapshot_id=evidence.snapshot_id,
        snapshot_hash=evidence.snapshot_hash,
        created_at=utc_now(),
    )


def _evidence_from_row(row: EvidenceRecordRow) -> Evidence:
    """Convert an EvidenceRecordRow to an Evidence domain model."""
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
        section=row.section,
        paragraph_index=row.paragraph_index,
        table_id=row.table_id,
        row_id=row.row_id,
        quote_span=tuple(row.quote_span) if row.quote_span else None,
        snapshot_id=row.snapshot_id,
        snapshot_hash=row.snapshot_hash,
    )


def _claim_to_row(claim: Claim) -> EvidenceClaimRow:
    """Convert a Claim domain model to a database row."""
    return EvidenceClaimRow(
        claim_id=claim.claim_id,
        claim_type=claim.claim_type.value,
        statement=claim.statement,
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
    """Convert an EvidenceClaimRow to a Claim domain model."""
    return Claim(
        claim_id=row.claim_id,
        claim_type=ClaimType(row.claim_type),
        statement=row.statement,
        fact_or_inference=FactOrInference(row.fact_or_inference),
        evidence_ids=list(row.evidence_ids),
        confidence=row.confidence,
        conflicts=[ConflictRecord(**item) for item in row.conflicts],
        effective_at=row.effective_at,
        locator=row.locator,
        symbol=row.symbol,
    )


def _audit_to_row(audit: ValidationAuditRecord) -> EvidenceValidationAuditRow:
    """Convert a ValidationAuditRecord domain model to a database row."""
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
    """Convert an EvidenceValidationAuditRow to a ValidationAuditRecord model."""
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
    """Convert a ResearchEvidenceRow to a ResearchEvidenceLink model."""
    return ResearchEvidenceLink(
        research_item_id=row.research_item_id,
        claim_id=row.claim_id,
        evidence_id=row.evidence_id,
        role=row.role,
        rank=row.rank,
        created_at=row.created_at,
    )
