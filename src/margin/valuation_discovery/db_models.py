"""SQLAlchemy rows for v0.2 valuation discovery."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class UniverseDefinitionRow(Base):
    """Universe definition data, including built-ins and future custom pools."""

    __tablename__ = "universe_definitions"

    definition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    universe_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rule_code: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class UniverseVersionRow(Base):
    """Immutable universe definition version."""

    __tablename__ = "universe_versions"
    __table_args__ = (
        Index("ix_universe_versions_code_system", "universe_code", "system_from"),
    )

    universe_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    definition_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    universe_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class UniverseSnapshotRow(Base):
    """Frozen universe membership snapshot consumed by quant."""

    __tablename__ = "universe_snapshots"
    __table_args__ = (
        Index("ix_universe_snapshots_code_time", "universe_code", "business_at", "known_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    universe_code: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    business_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    security_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    membership_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UniverseMembershipRow(Base):
    """Bitemporal universe membership row."""

    __tablename__ = "universe_memberships"
    __table_args__ = (
        Index(
            "ix_universe_memberships_code_valid_system",
            "universe_code",
            "valid_from",
            "system_from",
        ),
        Index("ix_universe_memberships_security_time", "security_id", "valid_from"),
    )

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    universe_code: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weight: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_lineage_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class QuantInputSnapshotRow(Base):
    """Frozen PIT-safe quant input snapshot."""

    __tablename__ = "quant_input_snapshots"
    __table_args__ = (
        Index("ix_quant_input_snapshots_scope_decision", "scope_version_id", "decision_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    security_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    required_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    optional_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quant_feature_set_version_id: Mapped[str | None] = mapped_column(String(64))
    user_indicator_view_version_id: Mapped[str | None] = mapped_column(String(64))
    market_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_required: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    data_status: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    freshness_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    pit_validation_errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    corporate_action_adjustment_version: Mapped[str | None] = mapped_column(String(64))
    industry_snapshot_id: Mapped[str | None] = mapped_column(String(96))
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantInputSnapshotFactRow(Base):
    """Lineage from a quant input snapshot to warehouse facts."""

    __tablename__ = "quant_input_snapshot_facts"
    __table_args__ = (
        Index("ix_quant_input_snapshot_facts_snapshot", "snapshot_id", "security_id"),
    )

    fact_ref_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_id: Mapped[str] = mapped_column(String(96), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)


class QuantScreenRunRow(Base):
    """Append-only quant screen run."""

    __tablename__ = "quant_screen_runs"
    __table_args__ = (
        Index("ix_quant_screen_runs_scope_decision", "scope_version_id", "decision_at"),
    )

    quant_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantScreenResultRow(Base):
    """Single-security quant result."""

    __tablename__ = "quant_screen_results"
    __table_args__ = (
        Index("ix_quant_screen_results_security_decision", "security_id", "created_at"),
        Index("ix_quant_screen_results_run_status", "quant_run_id", "screening_status"),
    )

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quant_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float)
    value_score: Mapped[float | None] = mapped_column(Float)
    growth_score: Mapped[float | None] = mapped_column(Float)
    momentum_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    rank_overall: Mapped[int | None] = mapped_column(Integer)
    rank_in_industry: Mapped[int | None] = mapped_column(Integer)
    screening_status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    research_guardrail: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    factor_details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantFactorValueRow(Base):
    """Individual factor values used to explain a quant result."""

    __tablename__ = "quant_factor_values"
    __table_args__ = (Index("ix_quant_factor_values_result_group", "result_id", "factor_group"),)

    factor_value_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_group: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_value: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ResearchRefreshEventRow(Base):
    """Append-only event emitted by the refresh state machine."""

    __tablename__ = "research_refresh_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    refresh_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValuationRefreshRunRow(Base):
    """Durable valuation discovery refresh run."""

    __tablename__ = "valuation_refresh_runs"
    __table_args__ = (
        Index("ix_valuation_refresh_runs_scope_decision", "scope_version_id", "decision_at"),
    )

    refresh_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValuationRefreshStepRow(Base):
    """Append-only refresh step event."""

    __tablename__ = "valuation_refresh_steps"

    step_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    refresh_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_ref: Mapped[str | None] = mapped_column(String(256))
    error_code: Mapped[str | None] = mapped_column(String(128))


class ResearchContextSnapshotRow(Base):
    """Frozen research context made available to AI/dashboard modules."""

    __tablename__ = "research_context_snapshots"
    __table_args__ = (
        Index("ix_research_context_snapshots_security_scope", "security_id", "scope_version_id"),
    )

    context_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValuationAssessmentRow(Base):
    """Deterministic valuation assessment."""

    __tablename__ = "valuation_assessments"
    __table_args__ = (
        Index("ix_valuation_assessments_security_decision", "security_id", "decision_at"),
        Index("ix_valuation_assessments_scope_decision", "scope_version_id", "decision_at"),
    )

    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valuation_model: Mapped[str] = mapped_column(String(128), nullable=False)
    intrinsic_value: Mapped[float | None] = mapped_column(Float)
    margin_of_safety: Mapped[float | None] = mapped_column(Float)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValuationAssessmentEvidenceRow(Base):
    """Evidence edge for a valuation assessment."""

    __tablename__ = "valuation_assessment_evidence"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(String(96), nullable=False)
    claim_id: Mapped[str | None] = mapped_column(String(96))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EffectiveAssessmentPointerRow(Base):
    """Current effective assessment pointer."""

    __tablename__ = "effective_assessment_pointers"
    __table_args__ = (
        Index("ix_effective_assessment_security_scope", "security_id", "scope_version_id"),
    )

    pointer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_assessment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_assessment_id: Mapped[str | None] = mapped_column(String(64))
    assessment_freshness: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    stale_reason: Mapped[str | None] = mapped_column(String(128))
    last_successful_data_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_news_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConfidenceComponentRow(Base):
    """Deterministic confidence component."""

    __tablename__ = "confidence_components"

    component_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    component_name: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
