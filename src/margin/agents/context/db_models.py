"""SQLAlchemy rows for v1 Context Engineering persistence."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ContextPackRow(Base):
    """One immutable ContextPack materialized for an Agent run."""

    __tablename__ = "context_packs"
    __table_args__ = (
        Index("ix_context_packs_run_id", "run_id"),
        Index("ix_context_packs_agent", "created_for_agent"),
        {"schema": "agent"},
    )

    context_pack_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    created_for_agent: Mapped[str] = mapped_column(Text, nullable=False)
    user_goal: Mapped[str] = mapped_column(Text, nullable=False)
    token_budget: Mapped[int] = mapped_column(nullable=False)
    policy_snapshot_ref: Mapped[str | None] = mapped_column(Text)
    pack_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pack_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextFactRow(Base):
    """One queryable fact extracted into a ContextPack."""

    __tablename__ = "context_facts"
    __table_args__ = (
        Index("ix_context_facts_pack", "context_pack_id"),
        Index("ix_context_facts_subject", "subject_type", "subject_id"),
        Index("ix_context_facts_type", "fact_type"),
        Index("ix_context_facts_available_at", "available_at"),
        {"schema": "agent"},
    )

    fact_id: Mapped[str] = mapped_column(Text, primary_key=True)
    context_pack_id: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict | None] = mapped_column(JSONB)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    artifact_refs: Mapped[list[str]] = mapped_column(
        "source_artifact_refs",
        JSONB,
        nullable=False,
        default=list,
    )
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_locators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    freshness_status: Mapped[str] = mapped_column(Text, nullable=False)
    pii_or_secret_risk: Mapped[bool] = mapped_column(nullable=False)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextOmissionRow(Base):
    """One reason an artifact or fact was excluded from a ContextPack."""

    __tablename__ = "context_omissions"
    __table_args__ = (
        Index("ix_context_omissions_pack", "context_pack_id"),
        {"schema": "agent"},
    )

    omission_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_pack_id: Mapped[str] = mapped_column(Text, nullable=False)
    omitted_ref: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DomainContextCapsuleRow(Base):
    """One immutable compressed domain context capsule."""

    __tablename__ = "domain_context_capsules"
    __table_args__ = (
        Index("ix_domain_capsules_run", "run_id"),
        Index("ix_domain_capsules_domain", "domain"),
        {"schema": "agent"},
    )

    capsule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    domain_task_id: Mapped[str] = mapped_column(Text, nullable=False)
    expert_agent: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    capsule_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capsule_hash: Mapped[str] = mapped_column(Text, nullable=False)
    output_artifact_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    audit_report_ref: Mapped[str | None] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactLineageEdgeRow(Base):
    """One immutable context lineage edge between artifacts or evidence refs."""

    __tablename__ = "artifact_lineage_edges"
    __table_args__ = (
        UniqueConstraint("from_ref", "to_ref", "edge_type", name="uq_artifact_lineage_edge"),
        Index("ix_artifact_lineage_run", "run_id"),
        Index("ix_artifact_lineage_to", "to_ref"),
        {"schema": "agent"},
    )

    edge_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    from_ref: Mapped[str] = mapped_column(Text, nullable=False)
    to_ref: Mapped[str] = mapped_column(Text, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
