"""SQLAlchemy rows for v0.2 valuation discovery."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class QuantInputSnapshotRow(Base):
    """Frozen PIT-safe quant input snapshot.."""

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
    feature_snapshot_id: Mapped[str | None] = mapped_column(String(64))
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
    """Lineage from a quant input snapshot to warehouse facts.."""

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
    """Append-only quant screen run.."""

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
    """Single-security quant result.."""

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
    """Individual factor values used to explain a quant result.."""

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


class ResearchContextSnapshotRow(Base):
    """Frozen research context made available to AI/dashboard modules.."""

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
    """Deterministic valuation assessment.."""

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
    """Evidence edge for a valuation assessment.."""

    __tablename__ = "valuation_assessment_evidence"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(String(96), nullable=False)
    claim_id: Mapped[str | None] = mapped_column(String(96))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EffectiveAssessmentPointerRow(Base):
    """Current effective assessment pointer.."""

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


class QuantFeatureSnapshotRow(Base):
    """Fourth-layer quant input feature snapshot materialized from layer 3.."""

    __tablename__ = "quant_feature_snapshots"
    __table_args__ = (
        Index(
            "ix_quant_feature_snapshots_scope_decision",
            "scope_version_id",
            "decision_at",
        ),
        Index(
            "ix_quant_feature_snapshots_universe",
            "universe_snapshot_id",
            "decision_at",
        ),
    )

    feature_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    feature_set_version_id: Mapped[str | None] = mapped_column(String(64))
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    lineage_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantFeatureRowRow(Base):
    """One materialized feature row consumed by the quant layer.."""

    __tablename__ = "quant_feature_rows"
    __table_args__ = (
        Index("ix_quant_feature_rows_snapshot_security", "feature_snapshot_id", "security_id"),
    )

    row_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    feature_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    industry_id: Mapped[str | None] = mapped_column(String(128))
    features_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisSnapshotRow(Base):
    """Fourth-layer analysis snapshot exposed to upper services and AI tools.."""

    __tablename__ = "analysis_snapshots"
    __table_args__ = (
        Index(
            "ix_analysis_snapshots_security_scope_decision",
            "security_id",
            "scope_version_id",
            "decision_at",
        ),
        Index(
            "ix_analysis_snapshots_quant_run",
            "quant_run_id",
            "security_id",
        ),
    )

    analysis_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    quant_run_id: Mapped[str | None] = mapped_column(String(64))
    quant_result_id: Mapped[str | None] = mapped_column(String(64))
    input_snapshot_id: Mapped[str | None] = mapped_column(String(64))
    strategy_version_id: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str | None] = mapped_column(String(96))
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisMetricRow(Base):
    """Structured metric materialized into the Analysis Mart.."""

    __tablename__ = "analysis_metrics"
    __table_args__ = (
        Index("ix_analysis_metrics_snapshot_group", "analysis_snapshot_id", "metric_group"),
    )

    metric_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    analysis_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(256), nullable=False)
    metric_group: Mapped[str] = mapped_column(String(64), nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    percentile_market: Mapped[float | None] = mapped_column(Float)
    percentile_industry: Mapped[float | None] = mapped_column(Float)
    rank_market: Mapped[int | None] = mapped_column(Integer)
    rank_industry: Mapped[int | None] = mapped_column(Integer)
    source_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisFindingRow(Base):
    """Structured analysis finding derived from quant, canonical, or AI outputs.."""

    __tablename__ = "analysis_findings"
    __table_args__ = (
        Index("ix_analysis_findings_snapshot_type", "analysis_snapshot_id", "finding_type"),
    )

    finding_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    analysis_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisEvidenceLinkRow(Base):
    """Evidence and lineage edge for one Analysis Mart snapshot.."""

    __tablename__ = "analysis_evidence_links"
    __table_args__ = (
        Index("ix_analysis_evidence_links_snapshot", "analysis_snapshot_id"),
        Index("ix_analysis_evidence_links_evidence", "evidence_id"),
    )

    link_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    analysis_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_id: Mapped[str | None] = mapped_column(String(96))
    metric_id: Mapped[str | None] = mapped_column(String(96))
    evidence_id: Mapped[str | None] = mapped_column(String(96))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
