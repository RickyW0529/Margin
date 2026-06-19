"""Domain models for module 09 holdings monitoring."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now
from margin.portfolio.models import PositionHealthStatus, ThesisStatus


class AlertPriority(StrEnum):
    """Alert priority levels defined by product design §10.2."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AlertType(StrEnum):
    """Supported deterministic holdings-monitoring alert types."""

    DATA_QUALITY = "data_quality"
    NEW_DISCLOSURE = "new_disclosure"
    NEGATIVE_EVENT = "negative_event"
    PRICE_INVALIDATION = "price_invalidation"
    MODEL_RANK_CHANGE = "model_rank_change"
    INDUSTRY_EXPOSURE = "industry_exposure"
    VALUATION_TARGET = "valuation_target"
    STRATEGY_FAILURE = "strategy_failure"
    KEY_EVENT_PENDING = "key_event_pending"


class ReviewDecision(StrEnum):
    """Manual review decisions after an alert."""

    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"
    WATCH = "watch"
    IGNORE = "ignore"


class AlertEvent(BaseModel):
    """Append-only alert emitted by the holdings monitoring rule engine."""

    alert_id: str = Field(default_factory=lambda: f"al_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    symbol: str
    alert_type: AlertType
    severity: AlertPriority = AlertPriority.P2
    message: str
    rule_name: str
    triggered_at: datetime = Field(default_factory=utc_now)
    evidence_refs: list[str] = Field(default_factory=list)
    changed_thesis: bool = False
    acknowledged_at: datetime | None = None

    model_config = {"frozen": True}

    @field_validator("triggered_at", "acknowledged_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class PositionMonitoringSnapshot(BaseModel):
    """Result of one deterministic position monitoring evaluation."""

    position_id: str
    portfolio_id: str
    symbol: str
    health_status: PositionHealthStatus
    thesis_status: ThesisStatus
    evaluated_at: datetime = Field(default_factory=utc_now)
    reasons: list[str] = Field(default_factory=list)
    alerts: list[AlertEvent] = Field(default_factory=list)
    data_missing: bool = False

    model_config = {"frozen": True}

    @field_validator("evaluated_at")
    @classmethod
    def normalize_evaluated_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class PositionReviewRecord(BaseModel):
    """Append-only manual review record after an alert."""

    review_id: str = Field(default_factory=lambda: f"rv_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    alert_id: str | None = None
    decision: ReviewDecision
    rationale: str
    action_taken_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("action_taken_at", "created_at")
    @classmethod
    def normalize_review_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class OperationHistoryEntry(BaseModel):
    """Unified operation-history entry for a position detail view."""

    event_id: str
    position_id: str
    event_type: str
    occurred_at: datetime
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class BehaviorMetric(BaseModel):
    """User behavior metric derived from alert and review timestamps."""

    metric_id: str = Field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    alert_id: str
    review_id: str
    action_latency_seconds: int | None = None
    signal_execution_gap: str | None = None

    model_config = {"frozen": True}
