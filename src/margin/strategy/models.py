"""Domain models for the strategy configuration module."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator

from margin.news.models import ensure_utc, utc_now


class StrategyState(StrEnum):
    """Lifecycle states of a strategy version.."""

    DRAFT = "draft"
    VALIDATING = "validating"
    INVALID = "invalid"
    BACKTESTING = "backtesting"
    PAPER_TRADING = "paper_trading"
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"


class ConfigLifecycle(StrEnum):
    """Lifecycle states for v0.2 versioned configuration resources.."""

    DRAFT = "draft"
    REVIEW = "review"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class IndicatorSelectionMode(StrEnum):
    """How a user-facing indicator view selects visible indicators.."""

    ALL = "all"
    INCLUDE = "include"
    EXCLUDE = "exclude"


class ProviderConfigVersion(BaseModel):
    """Versioned non-sensitive provider configuration.."""

    version_id: str
    provider_name: str
    provider_type: str
    owner_id: str = "local-admin"
    base_url: str | None = None
    model_name: str | None = None
    enabled: bool = True
    non_sensitive_config: dict[str, Any] = Field(default_factory=dict)
    secret_version_id: str | None = None
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize creation time.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


class UniverseDefinitionVersion(BaseModel):
    """Versioned stock universe definition.."""

    version_id: str
    owner_id: str = "local-admin"
    universe_code: str
    name: str
    selection_rule: dict[str, Any] = Field(default_factory=dict)
    member_security_ids: tuple[str, ...] = ()
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class IndicatorViewVersion(BaseModel):
    """User-facing indicator visibility configuration.."""

    version_id: str
    owner_id: str
    mode: IndicatorSelectionMode = IndicatorSelectionMode.ALL
    included_indicators: tuple[str, ...] = ()
    excluded_indicators: tuple[str, ...] = ()
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)

    def visible_indicator_ids(self, all_indicator_ids: Sequence[str]) -> tuple[str, ...]:
        """Return indicators visible to the user without changing quant requirements.

        Args:
            all_indicator_ids: Sequence[str]: .

        Returns:
            tuple[str, ...]: .
        """
        if self.mode is IndicatorSelectionMode.ALL:
            return tuple(all_indicator_ids)
        if self.mode is IndicatorSelectionMode.INCLUDE:
            included = set(self.included_indicators)
            return tuple(item for item in all_indicator_ids if item in included)
        excluded = set(self.excluded_indicators)
        return tuple(item for item in all_indicator_ids if item not in excluded)


class QuantFeatureSetVersion(BaseModel):
    """Versioned quant input feature requirements.."""

    version_id: str
    owner_id: str = "local-admin"
    required_indicators: tuple[str, ...]
    optional_indicators: tuple[str, ...] = ()
    history_days: int = Field(default=750, ge=1)
    fallback_policy: str = "mark_missing"
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class QuantStrategyVersion(BaseModel):
    """Versioned quant strategy configuration.."""

    version_id: str
    owner_id: str = "local-admin"
    strategy_family: str = "default"
    factor_weights: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    calibration_report_id: str | None = None
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class UserStylePromptVersion(BaseModel):
    """Versioned user style prompt overlay.."""

    version_id: str
    owner_id: str
    prompt_name: str = "default"
    content: str
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class ToolPolicyVersionRef(BaseModel):
    """Reference to a versioned tool policy.."""

    version_id: str
    owner_id: str = "local-admin"
    allowed_tool_names: tuple[str, ...] = ()
    denied_tool_names: tuple[str, ...] = ()
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class ResearchScopeVersion(BaseModel):
    """Frozen set of config version IDs bound to downstream runs.."""

    version_id: str
    owner_id: str = "local-admin"
    universe_version_id: str
    indicator_view_version_id: str
    quant_feature_set_version_id: str
    quant_strategy_version_id: str
    ai_prompt_version_id: str
    canonical_rule_version: str
    tool_policy_version_id: str
    provider_config_version_ids: tuple[str, ...] = ()
    lifecycle: ConfigLifecycle = ConfigLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope_hash(self) -> str:
        """Return deterministic hash over referenced version IDs and canonical rules.

        Returns:
            str: .
        """
        payload = {
            "universe_version_id": self.universe_version_id,
            "indicator_view_version_id": self.indicator_view_version_id,
            "quant_feature_set_version_id": self.quant_feature_set_version_id,
            "quant_strategy_version_id": self.quant_strategy_version_id,
            "ai_prompt_version_id": self.ai_prompt_version_id,
            "canonical_rule_version": self.canonical_rule_version,
            "tool_policy_version_id": self.tool_policy_version_id,
            "provider_config_version_ids": list(self.provider_config_version_ids),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ProhibitedOutput(StrEnum):
    """Outputs that strategies must never produce.."""

    GUARANTEED_RETURN = "GUARANTEED_RETURN"
    DIRECT_BUY_SELL_ORDER = "DIRECT_BUY_SELL_ORDER"


class AIConfig(BaseModel):
    """AI provider and prompt settings for a strategy.."""

    provider: str = "openai"
    model: str = "deepseek-v4-pro"
    websearch_provider: str = "tavily"
    system_prompt_template: str = "default"
    custom_instructions: str = ""


class EvidenceConfig(BaseModel):
    """Evidence requirements for a strategy.."""

    required_levels: list[str] = Field(default_factory=lambda: ["L1", "L2", "L3"])
    min_evidence_count: int = 3

    @field_validator("min_evidence_count")
    @classmethod
    def validate_min_evidence(cls, value: int) -> int:
        """Ensure the minimum evidence count is non-negative.

        Args:
            value: int: .

        Returns:
            int: .
        """
        if value < 0:
            raise ValueError("min_evidence_count must be non-negative")
        return value


class DecisionConfig(BaseModel):
    """Decision boundaries and prohibited outputs.."""

    research_states: list[str] = Field(
        default_factory=lambda: ["research_candidate", "watch", "abstained"]
    )
    prohibited_outputs: list[str] = Field(default_factory=list)


class ValuationConfig(BaseModel):
    """Valuation method configuration.."""

    method: str = "pe"
    eps: float = 1.0
    pe: float = 10.0


class QualityConfig(BaseModel):
    """Data quality and source constraints.."""

    min_source_level: str = "L3"
    require_primary_source: bool = True


class RiskConfig(BaseModel):
    """Risk limits for a strategy.."""

    max_drawdown: float | None = None
    risk_score_threshold: float = 0.7


class StrategyConfig(BaseModel):
    """Complete user-editable strategy configuration.."""

    universe: list[str] = Field(default_factory=lambda: ["000001.SZ"])
    horizon: int = Field(default=90, ge=1)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)


class PromptLayer(BaseModel):
    """A single layer in the final merged prompt.."""

    layer: str
    content: str
    editable: bool = True

    model_config = {"frozen": True}


class StrategySandboxResult(BaseModel):
    """Result of running a strategy through the sandbox.."""

    validation_ok: bool = False
    sample_run_ok: bool = False
    backtest_ok: bool = False
    data_leak_ok: bool = False
    cost_ok: bool = False
    preview_ok: bool = False
    messages: list[str] = Field(default_factory=list)


class StrategyVersion(BaseModel):
    """Immutable snapshot of a strategy configuration.."""

    strategy_id: str
    version_id: str = Field(default_factory=lambda: f"sv_{uuid.uuid4().hex[:12]}")
    name: str
    description: str = ""
    config: StrategyConfig
    prompt_layers: tuple[PromptLayer, ...] = ()
    state: StrategyState = StrategyState.DRAFT
    prompt_version: str = ""
    sandbox_result: StrategySandboxResult | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize the creation timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


class StrategyProfile(BaseModel):
    """Mutable profile owning a sequence of immutable strategy versions.."""

    strategy_id: str = Field(default_factory=lambda: f"st_{uuid.uuid4().hex[:12]}")
    owner_id: str
    name: str
    active_version_id: str = ""
    versions: tuple[StrategyVersion, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Normalize profile timestamps to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    def with_version(self, version: StrategyVersion) -> StrategyProfile:
        """Return a new profile with the given version appended.

        Args:
            version: StrategyVersion: .

        Returns:
            StrategyProfile: .
        """
        return self.model_copy(
            update={
                "versions": self.versions + (version,),
                "updated_at": utc_now(),
            }
        )

    def with_active_version(self, version_id: str) -> StrategyProfile:
        """Return a new profile with the active version updated.

        Args:
            version_id: str: .

        Returns:
            StrategyProfile: .
        """
        return self.model_copy(
            update={
                "active_version_id": version_id,
                "updated_at": utc_now(),
            }
        )


class StrategyTemplateMeta(BaseModel):
    """Metadata for a built-in strategy template.."""

    template_id: str
    name: str
    description: str
    category: str

    model_config = {"frozen": True}
