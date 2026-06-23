"""Domain models for v0.2 valuation discovery.

The models in this module are deliberately provider-free. They describe frozen
inputs and append-only outputs that can be persisted, audited, and replayed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    """utc now."""
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    """new id."""
    return f"{prefix}_{uuid4().hex[:16]}"


def _hash_payload(payload: Any) -> str:
    """hash payload."""
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _normalize_datetime(value: datetime | None) -> datetime | None:
    """normalize datetime."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UniverseCode(StrEnum):
    """Built-in universe codes.

    New custom pools should be stored as data/rule versions. They do not require
    changing this enum unless they become first-class built-ins.
    """

    CSI300 = "CSI300"
    CSI500 = "CSI500"
    ALL_A = "ALL_A"


class ScreeningStatus(StrEnum):
    """Quant screening result, independent from data/risk/review state."""

    PASS = "pass"
    NEAR_THRESHOLD = "near_threshold"
    WATCHLIST = "watchlist"
    REJECT = "reject"


class DataStatus(StrEnum):
    """Data quality and PIT status for a quant result."""

    OK = "ok"
    INSUFFICIENT = "insufficient"
    PIT_DEGRADED = "pit_degraded"


class ResearchGuardrail(StrEnum):
    """Research and trading-discipline guardrails.

    These values are not direct buy/sell instructions.
    """

    RESEARCH_ALLOWED = "research_allowed"
    LIMITED_RESEARCH = "limited_research"
    RESEARCH_BLOCKED = "research_blocked"
    OVERHEAT_CAUTION = "overheat_caution"
    CONFIDENCE_REDUCED = "confidence_reduced"
    THESIS_RECHECK_REQUIRED = "thesis_recheck_required"


class RefreshStep(StrEnum):
    """Durable refresh state machine steps."""

    RESOLVE_SCOPE = "resolve_scope"
    SNAPSHOT_UNIVERSE = "snapshot_universe"
    BUILD_QUANT_INPUT = "build_quant_input"
    RUN_QUANT = "run_quant"
    SELECT_NEWS_TARGETS = "select_news_targets"
    ACQUIRE_NEWS = "acquire_news"
    INDEX_TEXT = "index_text"
    BUILD_EVIDENCE = "build_evidence"
    AI_REVIEW = "ai_review"
    PUBLISH_CONTEXT = "publish_context"
    UPDATE_DASHBOARD = "update_dashboard"


class FrozenModel(BaseModel):
    """Base class for immutable domain records."""

    model_config = ConfigDict(frozen=True)


class UniverseDefinition(FrozenModel):
    """Versioned universe definition header."""

    definition_id: str = Field(default_factory=lambda: _new_id("univ_def"))
    universe_code: UniverseCode | str
    name: str
    description: str = ""
    rule_code: str
    rule_config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str = "system"

    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class UniverseVersion(FrozenModel):
    """Immutable universe rule/materialization version."""

    universe_version_id: str = Field(default_factory=lambda: _new_id("univ_ver"))
    definition_id: str
    universe_code: UniverseCode | str
    version: str
    effective_from: datetime
    effective_to: datetime | None = None
    system_from: datetime = Field(default_factory=_utc_now)
    system_to: datetime | None = None
    source: str
    quality: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalize_effective_from = field_validator("effective_from")(_normalize_datetime)
    _normalize_effective_to = field_validator("effective_to")(_normalize_datetime)
    _normalize_system_from = field_validator("system_from")(_normalize_datetime)
    _normalize_system_to = field_validator("system_to")(_normalize_datetime)


class UniverseMembership(FrozenModel):
    """Bitemporal security membership inside a universe."""

    membership_id: str = Field(default_factory=lambda: _new_id("univ_mem"))
    universe_code: UniverseCode | str
    universe_version_id: str
    security_id: str
    valid_from: datetime
    valid_to: datetime | None = None
    system_from: datetime
    system_to: datetime | None = None
    weight: float | None = None
    rank: int | None = None
    source: str
    quality: str = "ok"
    raw_lineage_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalize_valid_from = field_validator("valid_from")(_normalize_datetime)
    _normalize_valid_to = field_validator("valid_to")(_normalize_datetime)
    _normalize_system_from = field_validator("system_from")(_normalize_datetime)
    _normalize_system_to = field_validator("system_to")(_normalize_datetime)

    def is_visible_at(self, *, business_at: datetime, known_at: datetime) -> bool:
        """Return whether this membership is valid and known at the supplied times."""
        business = _normalize_datetime(business_at)
        known = _normalize_datetime(known_at)
        assert business is not None
        assert known is not None
        valid_to = self.valid_to or datetime.max.replace(tzinfo=UTC)
        system_to = self.system_to or datetime.max.replace(tzinfo=UTC)
        return self.valid_from <= business < valid_to and self.system_from <= known < system_to


class UniverseSnapshot(FrozenModel):
    """Frozen universe membership list used by downstream quant."""

    snapshot_id: str = Field(default_factory=lambda: _new_id("univ_snap"))
    universe_code: UniverseCode | str
    universe_version_id: str
    business_at: datetime
    known_at: datetime
    security_ids: tuple[str, ...]
    membership_ids: tuple[str, ...] = ()
    input_hash: str = ""
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_business_at = field_validator("business_at")(_normalize_datetime)
    _normalize_known_at = field_validator("known_at")(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)

    def model_post_init(self, __context: Any) -> None:
        """model post init."""
        if self.input_hash:
            return
        payload = {
            "universe_code": str(self.universe_code),
            "universe_version_id": self.universe_version_id,
            "business_at": self.business_at,
            "known_at": self.known_at,
            "security_ids": self.security_ids,
            "membership_ids": self.membership_ids,
        }
        object.__setattr__(self, "input_hash", _hash_payload(payload))


class QuantInputSnapshot(FrozenModel):
    """Frozen PIT-safe input contract consumed by quant screening."""

    snapshot_id: str = Field(default_factory=lambda: _new_id("qis"))
    scope_version_id: str
    universe_snapshot_id: str
    decision_at: datetime
    known_at: datetime
    security_ids: tuple[str, ...]
    required_indicators: tuple[str, ...]
    optional_indicators: tuple[str, ...] = ()
    quant_feature_set: Any | None = None
    user_indicator_view: Any | None = None
    market_window_start: datetime | None = None
    market_window_end: datetime | None = None
    fact_refs: tuple[dict[str, Any], ...] = ()
    fact_count: int = 0
    missing_required: tuple[str, ...] = ()
    data_status: DataStatus = DataStatus.OK
    quality_flags: tuple[str, ...] = ()
    freshness_flags: tuple[str, ...] = ()
    pit_validation_errors: tuple[str, ...] = ()
    corporate_action_adjustment_version: str | None = None
    industry_snapshot_id: str | None = None
    input_hash: str = ""
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_decision_at = field_validator("decision_at")(_normalize_datetime)
    _normalize_known_at = field_validator("known_at")(_normalize_datetime)
    _normalize_market_window_start = field_validator("market_window_start")(_normalize_datetime)
    _normalize_market_window_end = field_validator("market_window_end")(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)

    def model_post_init(self, __context: Any) -> None:
        """model post init."""
        if self.missing_required and self.data_status == DataStatus.OK:
            object.__setattr__(self, "data_status", DataStatus.INSUFFICIENT)
        if not self.input_hash:
            payload = {
                "scope_version_id": self.scope_version_id,
                "universe_snapshot_id": self.universe_snapshot_id,
                "decision_at": self.decision_at,
                "known_at": self.known_at,
                "security_ids": self.security_ids,
                "required_indicators": self.required_indicators,
                "optional_indicators": self.optional_indicators,
                "market_window_start": self.market_window_start,
                "market_window_end": self.market_window_end,
                "fact_refs": self.fact_refs,
                "missing_required": self.missing_required,
                "corporate_action_adjustment_version": self.corporate_action_adjustment_version,
                "industry_snapshot_id": self.industry_snapshot_id,
            }
            object.__setattr__(self, "input_hash", _hash_payload(payload))

    @property
    def is_valid(self) -> bool:
        """Return whether this snapshot can feed publishable quant runs."""
        return self.data_status == DataStatus.OK and not self.missing_required

    @property
    def missing_required_indicators(self) -> tuple[str, ...]:
        """Compatibility alias for required indicator gaps."""
        return self.missing_required


class QuantRun(FrozenModel):
    """Append-only quant run metadata."""

    quant_run_id: str = Field(default_factory=lambda: _new_id("qr"))
    input_snapshot_id: str
    scope_version_id: str
    strategy_version_id: str
    decision_at: datetime
    config_hash: str
    status: str = "created"
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_decision_at = field_validator("decision_at")(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class QuantResult(FrozenModel):
    """Single-security quant result with orthogonal status dimensions."""

    result_id: str = Field(default_factory=lambda: _new_id("qres"))
    quant_run_id: str
    security_id: str
    final_score: float
    quality_score: float | None = None
    value_score: float | None = None
    growth_score: float | None = None
    momentum_score: float | None = None
    risk_score: float | None = None
    rank_overall: int | None = None
    rank_in_industry: int | None = None
    screening_status: ScreeningStatus
    data_status: DataStatus = DataStatus.OK
    risk_flags: tuple[str, ...] = ()
    review_required: bool = False
    review_reasons: tuple[str, ...] = ()
    research_guardrail: ResearchGuardrail = ResearchGuardrail.RESEARCH_ALLOWED
    reason_summary: str = ""
    factor_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class ValuationAssessment(FrozenModel):
    """Deterministic valuation assessment record."""

    assessment_id: str = Field(default_factory=lambda: _new_id("va"))
    security_id: str
    scope_version_id: str
    decision_at: datetime
    valuation_model: str
    intrinsic_value: float | None = None
    margin_of_safety: float | None = None
    conclusion: str
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_decision_at = field_validator("decision_at")(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class ValuationAssessmentEvidence(FrozenModel):
    """Immutable evidence edge supporting one valuation assessment."""

    edge_id: str = Field(default_factory=lambda: _new_id("vae"))
    assessment_id: str
    evidence_id: str
    claim_id: str | None = None
    role: str = "supporting"
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class ConfidenceComponent(FrozenModel):
    """Deterministic confidence contribution used for calibration."""

    component_id: str = Field(default_factory=lambda: _new_id("conf"))
    assessment_id: str
    component_name: str
    score: float
    weight: float
    reason: str


class EffectiveAssessmentPointer(FrozenModel):
    """Current effective assessment pointer for one security/scope."""

    pointer_id: str = Field(default_factory=lambda: _new_id("eap"))
    security_id: str
    scope_version_id: str
    effective_assessment_id: str
    effective_from: datetime
    previous_assessment_id: str | None = None
    assessment_freshness: str = "current"
    stale_reason: str | None = None
    last_successful_data_check_at: datetime | None = None
    last_successful_news_check_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_effective_from = field_validator("effective_from")(_normalize_datetime)
    _normalize_last_successful_data_check_at = field_validator(
        "last_successful_data_check_at"
    )(_normalize_datetime)
    _normalize_last_successful_news_check_at = field_validator(
        "last_successful_news_check_at"
    )(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class RefreshRun(FrozenModel):
    """Durable valuation discovery refresh run header."""

    refresh_run_id: str = Field(default_factory=lambda: _new_id("vrr"))
    scope_version_id: str
    decision_at: datetime
    state: str = "pending"
    created_at: datetime = Field(default_factory=_utc_now)

    _normalize_decision_at = field_validator("decision_at")(_normalize_datetime)
    _normalize_created_at = field_validator("created_at")(_normalize_datetime)


class RefreshStepRecord(FrozenModel):
    """Durable valuation discovery refresh step event."""

    step_event_id: str = Field(default_factory=lambda: _new_id("vrs"))
    refresh_run_id: str
    step: RefreshStep
    state: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_ref: str | None = None
    error_code: str | None = None

    _normalize_started_at = field_validator("started_at")(_normalize_datetime)
    _normalize_finished_at = field_validator("finished_at")(_normalize_datetime)
