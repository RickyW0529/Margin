"""Domain models for the strategy configuration module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class StrategyState(StrEnum):
    """Lifecycle states of a strategy version."""

    DRAFT = "draft"
    VALIDATING = "validating"
    INVALID = "invalid"
    BACKTESTING = "backtesting"
    PAPER_TRADING = "paper_trading"
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"


class ProhibitedOutput(StrEnum):
    """Outputs that strategies must never produce."""

    GUARANTEED_RETURN = "GUARANTEED_RETURN"
    DIRECT_BUY_SELL_ORDER = "DIRECT_BUY_SELL_ORDER"


class AIConfig(BaseModel):
    """AI provider and prompt settings for a strategy."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    websearch_provider: str = "tavily"
    system_prompt_template: str = "default"
    custom_instructions: str = ""


class EvidenceConfig(BaseModel):
    """Evidence requirements for a strategy."""

    required_levels: list[str] = Field(default_factory=lambda: ["L1", "L2", "L3"])
    min_evidence_count: int = 3

    @field_validator("min_evidence_count")
    @classmethod
    def validate_min_evidence(cls, value: int) -> int:
        if value < 0:
            raise ValueError("min_evidence_count must be non-negative")
        return value


class DecisionConfig(BaseModel):
    """Decision boundaries and prohibited outputs."""

    research_states: list[str] = Field(
        default_factory=lambda: ["research_candidate", "watch", "abstained"]
    )
    position_review_states: list[str] = Field(
        default_factory=lambda: ["hold", "review", "close"]
    )
    prohibited_outputs: list[str] = Field(default_factory=list)


class ValuationConfig(BaseModel):
    """Valuation method configuration."""

    method: str = "pe"
    eps: float = 1.0
    pe: float = 10.0


class QualityConfig(BaseModel):
    """Data quality and source constraints."""

    min_source_level: str = "L3"
    require_primary_source: bool = True


class RiskConfig(BaseModel):
    """Risk limits for a strategy."""

    max_position_weight: float = 0.1
    max_sector_weight: float = 0.3
    max_drawdown: float | None = None
    risk_score_threshold: float = 0.7

    @field_validator("max_position_weight", "max_sector_weight")
    @classmethod
    def validate_weights(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError("weight must be in (0, 1]")
        return value


class StrategyConfig(BaseModel):
    """Complete user-editable strategy configuration."""

    universe: list[str] = Field(default_factory=lambda: ["000001.SZ"])
    horizon: int = Field(default=90, ge=1)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)


class PromptLayer(BaseModel):
    """A single layer in the final merged prompt."""

    layer: str
    content: str
    editable: bool = True

    model_config = {"frozen": True}


class StrategySandboxResult(BaseModel):
    """Result of running a strategy through the sandbox."""

    validation_ok: bool = False
    sample_run_ok: bool = False
    backtest_ok: bool = False
    data_leak_ok: bool = False
    cost_ok: bool = False
    preview_ok: bool = False
    messages: list[str] = Field(default_factory=list)


class StrategyVersion(BaseModel):
    """Immutable snapshot of a strategy configuration."""

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
        return ensure_utc(value)


class StrategyProfile(BaseModel):
    """Mutable profile owning a sequence of immutable strategy versions."""

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
        return ensure_utc(value)

    def with_version(self, version: StrategyVersion) -> StrategyProfile:
        """Return a new profile with the given version appended."""
        return self.model_copy(
            update={
                "versions": self.versions + (version,),
                "updated_at": utc_now(),
            }
        )

    def with_active_version(self, version_id: str) -> StrategyProfile:
        """Return a new profile with the active version updated."""
        return self.model_copy(
            update={
                "active_version_id": version_id,
                "updated_at": utc_now(),
            }
        )


class StrategyTemplateMeta(BaseModel):
    """Metadata for a built-in strategy template."""

    template_id: str
    name: str
    description: str
    category: str

    model_config = {"frozen": True}
