"""SQLAlchemy models for RAG evidence, claims, and validation audit persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class EvidenceRecordRow(Base):
    """Immutable evidence record derived from a retrievable document chunk.

    Attributes:
        evidence_id: Unique identifier of the evidence record.
        chunk_id: Identifier of the originating chunk.
        document_id: Identifier of the originating document.
        source_type: Source type string.
        source_url: Optional URL of the original source.
        source_name: Optional human-readable source name.
        source_level: Source level as an integer.
        quality_score: Optional explicit quality score.
        content_hash: Hash of the evidence content.
        content: Text content of the evidence.
        symbol: Optional ticker symbol.
        published_at: Publication timestamp (UTC).
        available_at: Availability timestamp (UTC).
        retrieved_at: Retrieval timestamp (UTC).
        page: Optional page number.
        section: Optional section name.
        paragraph_index: Optional paragraph index.
        table_id: Optional table identifier.
        row_id: Optional row identifier.
        quote_span: Optional character span stored as JSONB.
        snapshot_id: Optional snapshot identifier.
        snapshot_hash: Optional snapshot content hash.
        created_at: Timestamp when the row was created (UTC).
    """

    __tablename__ = "evidence_records"
    __table_args__ = (
        Index("ix_evidence_records_document", "document_id"),
        Index("ix_evidence_records_symbol_available", "symbol", "available_at"),
        Index("ix_evidence_records_content_hash", "content_hash"),
    )

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(128))
    source_level: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)
    section: Mapped[str | None] = mapped_column(Text)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    dom_path: Mapped[str | None] = mapped_column(Text)
    table_id: Mapped[str | None] = mapped_column(String(64))
    row_id: Mapped[str | None] = mapped_column(String(64))
    column_id: Mapped[str | None] = mapped_column(String(128))
    quote_span: Mapped[list[int] | None] = mapped_column(JSONB)
    snapshot_id: Mapped[str | None] = mapped_column(String(64))
    snapshot_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceClaimRow(Base):
    """Immutable structured claim produced from evidence references.

    Attributes:
        claim_id: Unique identifier of the claim.
        claim_type: Claim classification string.
        statement: Human-readable claim statement.
        fact_or_inference: Whether the claim is fact, inference, or unknown.
        evidence_ids: List of referenced evidence IDs stored as JSONB.
        confidence: Confidence score.
        conflicts: List of conflict dictionaries stored as JSONB.
        effective_at: Timestamp when the claim becomes effective (UTC).
        locator: Optional primary citation locator stored as JSONB.
        symbol: Optional ticker symbol.
        created_at: Timestamp when the row was created (UTC).
    """

    __tablename__ = "evidence_claims"
    __table_args__ = (
        Index("ix_evidence_claims_symbol_effective", "symbol", "effective_at"),
    )

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unsupported")
    fact_or_inference: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    conflicts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locator: Mapped[dict | None] = mapped_column(JSONB)
    symbol: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceValidationAuditRow(Base):
    """Append-only validation audit record for a claim.

    Attributes:
        audit_id: Unique identifier of the audit record.
        claim_id: Identifier of the audited claim.
        status: Validation status string.
        reason: Human-readable explanation.
        fail_reason: Optional categorized failure reason string.
        original_confidence: Claim confidence before capping.
        capped_confidence: Claim confidence after capping.
        conflicts_found: Number of conflicts detected.
        evidences_checked: Number of evidence items examined.
        evidences_passed: Number of evidence items that passed.
        requires_counter_review: Whether counter-review is required.
        checked_at: Timestamp when validation occurred (UTC).
        created_at: Timestamp when the row was created (UTC).
    """

    __tablename__ = "evidence_validation_audits"
    __table_args__ = (
        Index("ix_evidence_validation_audits_claim", "claim_id", "checked_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.claim_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    fail_reason: Mapped[str | None] = mapped_column(String(64))
    original_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    capped_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    conflicts_found: Mapped[int] = mapped_column(Integer, nullable=False)
    evidences_checked: Mapped[int] = mapped_column(Integer, nullable=False)
    evidences_passed: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_counter_review: Mapped[bool] = mapped_column(nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchEvidenceRow(Base):
    """Immutable link between a research item, a claim, and a supporting evidence item.

    Attributes:
        research_item_id: Identifier of the research item.
        claim_id: Identifier of the linked claim.
        evidence_id: Identifier of the linked evidence record.
        role: Role of the evidence in the research item.
        rank: Display order of the link.
        created_at: Timestamp when the row was created (UTC).
    """

    __tablename__ = "research_evidence"

    research_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.claim_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.evidence_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidencePackageRow(Base):
    """Frozen evidence package version served to research graph nodes."""

    __tablename__ = "evidence_packages"
    __table_args__ = (
        Index("ix_evidence_packages_security_decision", "security_id", "decision_at"),
        Index("ix_evidence_packages_parent", "parent_package_id"),
    )

    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    conflict_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    max_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieval_audit_id: Mapped[str | None] = mapped_column(String(64))
    parent_package_id: Mapped[str | None] = mapped_column(String(64))
    added_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidencePackageItemRow(Base):
    """Materialized package membership for evidence, claims, and conflicts."""

    __tablename__ = "evidence_package_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "version"],
            ["evidence_packages.package_id", "evidence_packages.version"],
            ondelete="RESTRICT",
        ),
        Index("ix_evidence_package_items_item", "item_type", "item_id"),
    )

    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimEvidenceLinkRow(Base):
    """Append-only relationship between a claim and evidence with a role."""

    __tablename__ = "claim_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "evidence_id",
            "role",
            name="uq_claim_evidence_link_role",
        ),
        Index("ix_claim_evidence_links_evidence", "evidence_id"),
    )

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.claim_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.evidence_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceConflictRow(Base):
    """Persisted deterministic conflict between two evidence records."""

    __tablename__ = "evidence_conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "version"],
            ["evidence_packages.package_id", "evidence_packages.version"],
            ondelete="RESTRICT",
        ),
        Index("ix_evidence_conflicts_package", "package_id", "version"),
        Index("ix_evidence_conflicts_security", "security_id"),
    )

    conflict_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.evidence_id", ondelete="RESTRICT"),
        nullable=False,
    )
    conflicting_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.evidence_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsContextEvidenceRow(Base):
    """Immutable link between a news context bundle and an evidence item."""

    __tablename__ = "news_context_evidence"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id",
            "evidence_id",
            name="uq_news_context_evidence",
        ),
        Index("ix_news_context_evidence_evidence", "evidence_id"),
    )

    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("news_context_bundles.bundle_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.evidence_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
