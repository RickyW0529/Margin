"""SQLAlchemy models for RAG evidence, claims, and validation audit persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class EvidenceRecordRow(Base):
    """Immutable evidence record derived from a retrievable document chunk."""

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
    section: Mapped[str | None] = mapped_column(Text)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    table_id: Mapped[str | None] = mapped_column(String(64))
    row_id: Mapped[str | None] = mapped_column(String(64))
    quote_span: Mapped[list[int] | None] = mapped_column(JSONB)
    snapshot_id: Mapped[str | None] = mapped_column(String(64))
    snapshot_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceClaimRow(Base):
    """Immutable structured claim produced from evidence references."""

    __tablename__ = "evidence_claims"
    __table_args__ = (
        Index("ix_evidence_claims_symbol_effective", "symbol", "effective_at"),
    )

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    fact_or_inference: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    conflicts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locator: Mapped[dict | None] = mapped_column(JSONB)
    symbol: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceValidationAuditRow(Base):
    """Append-only validation audit record for a claim."""

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
    """Immutable link between a research item, a claim, and a supporting evidence item."""

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
