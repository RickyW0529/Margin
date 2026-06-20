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
    """Append-only alert emitted by the holdings monitoring rule engine.

    Attributes:
        alert_id: Unique identifier of the alert.
        portfolio_id: Identifier of the portfolio that owns the position.
        position_id: Identifier of the monitored position.
        symbol: Traded symbol or ticker.
        alert_type: Categorized alert type.
        severity: Priority level of the alert.
        message: Human-readable alert message.
        rule_name: Name of the monitoring rule that triggered the alert.
        triggered_at: UTC timestamp when the alert was triggered.
        evidence_refs: References to evidence supporting the alert.
        changed_thesis: Whether the alert invalidates or changes the investment thesis.
        acknowledged_at: UTC timestamp when the alert was acknowledged, if any.
    """

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
        """Normalize timestamp fields to UTC.

        Args:
            value: A datetime value or None.

        Returns:
            The input normalized to UTC, or None if the input was None.
        """
        return ensure_utc(value) if value is not None else None


class PositionMonitoringSnapshot(BaseModel):
    """Result of one deterministic position monitoring evaluation.

    Attributes:
        position_id: Identifier of the evaluated position.
        portfolio_id: Identifier of the portfolio that owns the position.
        symbol: Traded symbol or ticker.
        health_status: Derived health status of the position.
        thesis_status: Derived thesis status of the position.
        evaluated_at: UTC timestamp when the evaluation ran.
        reasons: Human-readable reasons explaining the derived statuses.
        alerts: Alerts emitted during this evaluation.
        data_missing: Whether evaluation was blocked by missing price data.
    """

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
        """Normalize the evaluation timestamp to UTC.

        Args:
            value: A datetime value.

        Returns:
            The input normalized to UTC.
        """
        return ensure_utc(value)


class PositionReviewRecord(BaseModel):
    """Append-only manual review record after an alert.

    Attributes:
        review_id: Unique identifier of the review.
        portfolio_id: Identifier of the portfolio that owns the position.
        position_id: Identifier of the reviewed position.
        alert_id: Optional identifier of the alert that prompted the review.
        decision: Recorded review decision.
        rationale: Human-readable explanation of the review decision.
        action_taken_at: UTC timestamp when action was taken, if any.
        created_at: UTC timestamp when the review record was created.
    """

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
        """Normalize review timestamp fields to UTC.

        Args:
            value: A datetime value or None.

        Returns:
            The input normalized to UTC, or None if the input was None.
        """
        return ensure_utc(value) if value is not None else None


class OperationHistoryEntry(BaseModel):
    """Unified operation-history entry for a position detail view.

    Attributes:
        event_id: Unique identifier of the operation history event.
        position_id: Identifier of the related position.
        event_type: Type of event, such as "trade", "alert", or "review".
        occurred_at: UTC timestamp when the event occurred.
        summary: Human-readable summary of the event.
        metadata: Additional structured context for the event.
    """

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
        """Normalize the event timestamp to UTC.

        Args:
            value: A datetime value.

        Returns:
            The input normalized to UTC.
        """
        return ensure_utc(value)


class BehaviorMetric(BaseModel):
    """User behavior metric derived from alert and review timestamps.

    Attributes:
        metric_id: Unique identifier of the behavior metric.
        portfolio_id: Identifier of the portfolio that owns the position.
        position_id: Identifier of the related position.
        alert_id: Identifier of the alert that prompted the review.
        review_id: Identifier of the manual review.
        action_latency_seconds: Seconds between alert trigger and review action, if known.
        signal_execution_gap: Decision recorded for the review, represented as a string.
    """

    metric_id: str = Field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:12]}")
    portfolio_id: str
    position_id: str
    alert_id: str
    review_id: str
    action_latency_seconds: int | None = None
    signal_execution_gap: str | None = None

    model_config = {"frozen": True}
