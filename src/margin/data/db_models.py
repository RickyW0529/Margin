"""SQLAlchemy models for the v0.2 point-in-time data warehouse."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ProviderEndpointRow(Base):
    """Registered provider endpoint and its versioned sync policy."""

    __tablename__ = "provider_endpoints"
    __table_args__ = (
        UniqueConstraint("provider", "code", name="uq_provider_endpoint_provider_code"),
        Index("ix_provider_endpoints_domain", "domain"),
    )

    endpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    domain: Mapped[str] = mapped_column(String(48), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    backfill_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    revision_lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_limit_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataSyncRunRow(Base):
    """Durable data sync run covering one or more provider endpoints."""

    __tablename__ = "data_sync_runs"
    __table_args__ = (
        Index("ix_data_sync_runs_status", "status", "created_at"),
        Index("ix_data_sync_runs_provider", "provider", "created_at"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    endpoint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DataSyncWorkItemRow(Base):
    """Endpoint-level work item claimed by workers."""

    __tablename__ = "data_sync_work_items"
    __table_args__ = (
        UniqueConstraint("run_id", "endpoint_id", "cursor_before", name="uq_data_work_item"),
        Index("ix_data_work_items_claim", "status", "next_attempt_at", "created_at"),
    )

    work_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("data_sync_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str] = mapped_column(
        ForeignKey("provider_endpoints.endpoint_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    cursor_before: Mapped[str | None] = mapped_column(Text)
    cursor_after: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(96))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawDataSnapshotRow(Base):
    """Immutable raw provider payload snapshot metadata."""

    __tablename__ = "raw_data_snapshots"
    __table_args__ = (
        UniqueConstraint("provider", "endpoint_code", "payload_hash", name="uq_raw_data_payload"),
        Index("ix_raw_data_snapshots_payload_hash", "payload_hash"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_code: Mapped[str] = mapped_column(String(96), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    compression: Mapped[str] = mapped_column(String(24), nullable=False)
    raw_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SourceSchemaFieldRow(Base):
    """Observed source-field lifecycle for schema drift detection."""

    __tablename__ = "source_schema_fields"
    __table_args__ = (
        UniqueConstraint("provider", "endpoint_code", "field_name", name="uq_source_schema_field"),
        Index("ix_source_schema_fields_status", "status"),
    )

    field_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_code: Mapped[str] = mapped_column(String(96), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    inferred_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type_change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_values: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class IndicatorDefinitionRow(Base):
    """Canonical indicator definition."""

    __tablename__ = "indicator_definitions"

    indicator_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str | None] = mapped_column(String(16))
    required_for_quant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderIndicatorMappingRow(Base):
    """Mapping from provider/source fields to canonical indicators."""

    __tablename__ = "provider_indicator_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "endpoint_code",
            "source_field",
            "mapping_version",
            name="uq_provider_indicator_mapping",
        ),
    )

    mapping_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_code: Mapped[str] = mapped_column(String(96), nullable=False)
    source_field: Mapped[str] = mapped_column(String(128), nullable=False)
    indicator_id: Mapped[str] = mapped_column(String(96), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    transform: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StandardizedIndicatorFactRow(Base):
    """Append-only provider fact normalized to a canonical indicator."""

    __tablename__ = "standardized_indicator_facts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_fact_id", name="uq_standardized_provider_fact"),
        Index("ix_indicator_facts_security_indicator", "security_id", "indicator_id", "event_at"),
        Index("ix_indicator_facts_available", "available_at"),
    )

    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_code: Mapped[str] = mapped_column(String(96), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_id: Mapped[str] = mapped_column(String(96), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    text_value: Mapped[str | None] = mapped_column(Text)
    json_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(String(32))
    quality_score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("raw_data_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class CanonicalIndicatorValueRow(Base):
    """Selected canonical indicator value with all candidate facts preserved by reference."""

    __tablename__ = "canonical_indicator_values"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "indicator_id",
            "decision_at",
            "resolver_version",
            name="uq_canonical_value_resolver",
        ),
        Index("ix_canonical_values_security_indicator", "security_id", "indicator_id"),
        Index("ix_canonical_values_decision_at", "decision_at"),
    )

    canonical_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_id: Mapped[str] = mapped_column(String(96), nullable=False)
    indicator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    selected_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("standardized_indicator_facts.fact_id", ondelete="RESTRICT")
    )
    candidate_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    text_value: Mapped[str | None] = mapped_column(Text)
    json_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityMasterRow(Base):
    """Bitemporal security master record."""

    __tablename__ = "securities"
    __table_args__ = (Index("ix_securities_symbol", "symbol"),)

    security_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    listed_at: Mapped[date | None] = mapped_column(Date)
    delisted_at: Mapped[date | None] = mapped_column(Date)
    security_type: Mapped[str] = mapped_column(String(32), nullable=False, default="stock")
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_lineage_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class SecurityProviderIdentifierRow(Base):
    """Provider-specific identifier for a security with PIT validity."""

    __tablename__ = "security_provider_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_symbol", "valid_from", "system_from",
            name="uq_security_provider_identifier",
        ),
        Index("ix_security_provider_identifiers_security", "security_id"),
    )

    identifier_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(
        ForeignKey("securities.security_id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityIndustryMembershipRow(Base):
    """Bitemporal industry/taxonomy membership."""

    __tablename__ = "security_industry_memberships"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "taxonomy",
            "valid_from",
            "system_from",
            name="uq_security_industry_membership",
        ),
        Index(
            "ix_security_industry_lookup",
            "security_id",
            "taxonomy",
            "valid_from",
            "system_from",
        ),
    )

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(
        ForeignKey("securities.security_id", ondelete="CASCADE"), nullable=False
    )
    taxonomy: Mapped[str] = mapped_column(String(64), nullable=False)
    industry_code: Mapped[str] = mapped_column(String(64), nullable=False)
    industry_name: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(96), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_lineage_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class CorporateActionRow(Base):
    """Corporate action available at a point in time."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "action_type",
            "ex_date",
            "available_at",
            name="uq_corporate_action_pit",
        ),
        Index("ix_corporate_actions_security_available", "security_id", "available_at"),
    )

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(
        ForeignKey("securities.security_id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    payable_date: Mapped[date | None] = mapped_column(Date)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    share_ratio: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_data_snapshots.snapshot_id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AdjustedPriceSeriesRow(Base):
    """As-of adjusted price value keyed by adjustment policy version."""

    __tablename__ = "adjusted_price_series"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "trade_date",
            "decision_at",
            "adjustment_policy_version",
            name="uq_adjusted_price_series",
        ),
        Index("ix_adjusted_price_series_security", "security_id", "decision_at"),
    )

    adjusted_price_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(
        ForeignKey("securities.security_id", ondelete="CASCADE"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    adj_close: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    adjustment_factor: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    adjustment_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataQualityEventRow(Base):
    """Append-only quality issue detected during data ingestion or canonicalization."""

    __tablename__ = "data_quality_events"
    __table_args__ = (Index("ix_data_quality_events_security", "security_id", "created_at"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str | None] = mapped_column(String(32))
    indicator_id: Mapped[str | None] = mapped_column(String(96))
    issue_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataFreshnessStateRow(Base):
    """Expected and observed freshness by endpoint/domain."""

    __tablename__ = "data_freshness_states"
    __table_args__ = (
        UniqueConstraint("provider", "endpoint_code", "as_of_date", name="uq_data_freshness"),
        Index("ix_data_freshness_status", "status", "as_of_date"),
    )

    freshness_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_code: Mapped[str] = mapped_column(String(96), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RetentionDeletionAuditRow(Base):
    """Append-only audit for reference-aware data retention decisions."""

    __tablename__ = "retention_deletion_audits"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[str] = mapped_column(String(96), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
