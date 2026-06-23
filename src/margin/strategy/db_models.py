"""SQLAlchemy rows owned by the strategy configuration module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from margin.storage.base import Base


class StrategyProfileRow(Base):
    """Mutable strategy profile header."""

    __tablename__ = "strategy_profiles"

    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    active_version_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list[StrategyVersionRow]] = relationship(
        "StrategyVersionRow",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class StrategyVersionRow(Base):
    """Immutable strategy version snapshot."""

    __tablename__ = "strategy_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_profiles.strategy_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_layers: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    sandbox_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    profile: Mapped[StrategyProfileRow] = relationship(
        "StrategyProfileRow",
        back_populates="versions",
    )


class ProviderSecretVersionRow(Base):
    """Encrypted provider secret version metadata."""

    __tablename__ = "provider_secret_versions"
    __table_args__ = (
        Index(
            "uq_active_provider_secret_versions",
            "provider_name",
            "secret_name",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    secret_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(96), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    last_four: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderConfigVersionRow(Base):
    """Versioned non-sensitive provider configuration."""

    __tablename__ = "provider_config_versions"
    __table_args__ = (
        Index(
            "uq_active_provider_config_versions",
            "owner_id",
            "provider_name",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    non_sensitive_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secret_version_id: Mapped[str | None] = mapped_column(String(64))
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UniverseDefinitionVersionRow(Base):
    """Versioned universe definition."""

    __tablename__ = "universe_definition_versions"
    __table_args__ = (
        Index(
            "uq_active_universe_definition_versions",
            "owner_id",
            "universe_code",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    selection_rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    member_security_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IndicatorViewVersionRow(Base):
    """Versioned user-facing indicator view."""

    __tablename__ = "indicator_view_versions"
    __table_args__ = (
        Index(
            "uq_active_indicator_view_versions",
            "owner_id",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    included_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    excluded_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantFeatureSetVersionRow(Base):
    """Versioned quant feature requirements."""

    __tablename__ = "quant_feature_set_versions"
    __table_args__ = (
        Index(
            "uq_active_quant_feature_set_versions",
            "owner_id",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    required_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    optional_indicators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    history_days: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuantStrategyVersionRow(Base):
    """Versioned quant strategy configuration."""

    __tablename__ = "quant_strategy_versions"
    __table_args__ = (
        Index(
            "uq_active_quant_strategy_versions",
            "owner_id",
            "strategy_family",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_weights: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    calibration_report_id: Mapped[str | None] = mapped_column(String(96))
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserStylePromptVersionRow(Base):
    """Versioned user prompt overlay."""

    __tablename__ = "user_style_prompt_versions"
    __table_args__ = (
        Index(
            "uq_active_user_style_prompt_versions",
            "owner_id",
            "prompt_name",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolPolicyVersionRow(Base):
    """Versioned tool allow/deny policy used by AI orchestration."""

    __tablename__ = "tool_policy_versions"
    __table_args__ = (
        Index(
            "uq_active_tool_policy_versions",
            "owner_id",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed_tool_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    denied_tool_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchScopeVersionRow(Base):
    """Frozen references used by downstream data, quant, news, and AI runs."""

    __tablename__ = "research_scope_versions"
    __table_args__ = (
        Index(
            "uq_active_research_scope_versions",
            "owner_id",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
        ),
        Index("ix_research_scope_hash", "scope_hash"),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_view_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quant_feature_set_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quant_strategy_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_prompt_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_policy_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_config_version_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    scope_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategyConfigAuditRow(Base):
    """Append-only audit event for strategy configuration changes."""

    __tablename__ = "strategy_config_audits"
    __table_args__ = (
        Index(
            "uq_strategy_config_audit_idempotency",
            "actor_id",
            "action",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
