"""SQLAlchemy rows for domain-specific runtime configuration tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AgentFlowVersionRow(Base):
    """Versioned Agent flow DAG configuration.."""

    __tablename__ = "agent_flow_versions"
    __table_args__ = (
        Index(
            "uq_current_agent_flow_versions",
            "owner_id",
            "environment",
            "flow_id",
            unique=True,
            postgresql_where=text("is_current = true and lifecycle = 'active'"),
        ),
        Index(
            "ix_agent_flow_versions_lookup",
            "owner_id",
            "environment",
            "flow_id",
            "valid_from",
            "valid_to",
            "available_at",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    flow_id: Mapped[str] = mapped_column(String(96), nullable=False)
    flow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    step_graph_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_contract_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supersedes_version_id: Mapped[str | None] = mapped_column(String(96))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class QuantAgentProfileVersionRow(Base):
    """Versioned QuantAgent strategy profile configuration.."""

    __tablename__ = "quant_agent_profile_versions"
    __table_args__ = (
        Index(
            "uq_current_quant_agent_profile_versions",
            "owner_id",
            "environment",
            "profile_key",
            unique=True,
            postgresql_where=text("is_current = true and lifecycle = 'active'"),
        ),
        Index(
            "ix_quant_agent_profile_versions_lookup",
            "owner_id",
            "environment",
            "profile_key",
            "valid_from",
            "valid_to",
            "available_at",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(96), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(96), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(96), nullable=False)
    model_family: Mapped[str] = mapped_column(String(96), nullable=False)
    candidate_universe: Mapped[str] = mapped_column(String(96), nullable=False)
    score_name: Mapped[str] = mapped_column(String(128), nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    score_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    max_stock_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    min_cash: Mapped[float] = mapped_column(Float, nullable=False)
    exposure_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    daily_drawdown_stop: Mapped[float] = mapped_column(Float, nullable=False)
    cash_annual: Mapped[float] = mapped_column(Float, nullable=False)
    required_feature_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supersedes_version_id: Mapped[str | None] = mapped_column(String(96))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class ConfigResolutionSnapshotRow(Base):
    """Run-level resolved config lineage snapshot.."""

    __tablename__ = "config_resolution_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConfigResolutionSnapshotEntryRow(Base):
    """One version reference within a config resolution snapshot.."""

    __tablename__ = "config_resolution_snapshot_entries"
    __table_args__ = (
        Index(
            "uq_config_resolution_snapshot_entries",
            "snapshot_id",
            "domain",
            "config_key",
            unique=True,
        ),
    )

    entry_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(96),
        ForeignKey("config_resolution_snapshots.snapshot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version_id: Mapped[str] = mapped_column(String(96), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
