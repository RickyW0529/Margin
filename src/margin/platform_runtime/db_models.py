"""SQLAlchemy rows for platform and ops runtime tables."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class IdempotencyKeyRow(Base):
    """One idempotency replay record."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index("ix_idempotency_keys_expires", "expires_at"),
        {"schema": "platform"},
    )

    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_hash: Mapped[str | None] = mapped_column(Text)
    response_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuntimeEnvironmentRow(Base):
    """Runtime environment metadata for reproducibility."""

    __tablename__ = "runtime_environments"
    __table_args__ = ({"schema": "platform"},)

    environment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    environment_name: Mapped[str] = mapped_column(Text, nullable=False)
    app_version: Mapped[str | None] = mapped_column(Text)
    git_commit: Mapped[str | None] = mapped_column(Text)
    python_version: Mapped[str | None] = mapped_column(Text)
    node_version: Mapped[str | None] = mapped_column(Text)
    database_url_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlatformConfigResolutionSnapshotRow(Base):
    """Resolved runtime config snapshot for one run."""

    __tablename__ = "config_resolution_snapshots"
    __table_args__ = ({"schema": "platform"},)

    config_snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(Text)
    environment_id: Mapped[str | None] = mapped_column(Text)
    resolved_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolved_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventRow(Base):
    """One platform outbox event."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_pending", "status", "next_attempt_at"),
        {"schema": "platform"},
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeadLetterQueueRow(Base):
    """One redacted dead-letter entry."""

    __tablename__ = "dead_letter_queue"
    __table_args__ = ({"schema": "platform"},)

    dlq_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_redacted_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackfillCampaignRow(Base):
    """One backfill campaign runtime row."""

    __tablename__ = "backfill_campaigns"
    __table_args__ = ({"schema": "ops"},)

    campaign_id: Mapped[str] = mapped_column(Text, primary_key=True)
    campaign_name: Mapped[str] = mapped_column(Text, nullable=False)
    years: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    providers: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    endpoint_plan_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_run_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackfillPartitionRow(Base):
    """One idempotent backfill work partition."""

    __tablename__ = "backfill_partitions"
    __table_args__ = (
        Index("ix_backfill_partitions_status", "status", "provider_name", "endpoint_name"),
        UniqueConstraint(
            "campaign_id",
            "provider_name",
            "endpoint_name",
            "params_hash",
            name="uq_backfill_partition_params",
        ),
        {"schema": "ops"},
    )

    partition_id: Mapped[str] = mapped_column(Text, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_name: Mapped[str] = mapped_column(Text, nullable=False)
    partition_start: Mapped[date] = mapped_column(Date, nullable=False)
    partition_end: Mapped[date] = mapped_column(Date, nullable=False)
    params_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    params_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    raw_snapshot_refs: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    quality_report_ref: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackfillQualityReportRow(Base):
    """Quality report for a campaign or partition."""

    __tablename__ = "backfill_quality_reports"
    __table_args__ = ({"schema": "ops"},)

    quality_report_id: Mapped[str] = mapped_column(Text, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(Text, nullable=False)
    partition_id: Mapped[str | None] = mapped_column(Text)
    provider_name: Mapped[str | None] = mapped_column(Text)
    endpoint_name: Mapped[str | None] = mapped_column(Text)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    expected_rows: Mapped[int | None] = mapped_column(Integer)
    actual_rows: Mapped[int | None] = mapped_column(Integer)
    missing_dates: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    duplicate_key_count: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_drift_detected: Mapped[bool] = mapped_column(nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemHealthSnapshotRow(Base):
    """One component health snapshot."""

    __tablename__ = "system_health_snapshots"
    __table_args__ = ({"schema": "ops"},)

    health_snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    component_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataFreshnessStateRow(Base):
    """One dataset freshness state."""

    __tablename__ = "data_freshness_states"
    __table_args__ = ({"schema": "ops"},)

    freshness_state_id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str | None] = mapped_column(Text)
    latest_available_date: Mapped[date | None] = mapped_column(Date)
    latest_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_after_seconds: Mapped[int | None] = mapped_column(Integer)
    freshness_status: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
