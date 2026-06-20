"""Holdings monitoring API routes for the Margin API.

This module exposes endpoints for deterministic position monitoring,
including evaluation of monitoring rules, alert listing, manual review
recording, unified operation history, and behaviour-derived metrics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from margin.api.dependencies import get_monitoring_services
from margin.holdings_monitoring.models import (
    AlertEvent,
    BehaviorMetric,
    OperationHistoryEntry,
    PositionMonitoringSnapshot,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.service import MonitoringServiceBundle

router = APIRouter(prefix="/api/v1", tags=["monitoring"])
"""APIRouter exposing holdings-monitoring endpoints under ``/api/v1``."""

Services = Annotated[MonitoringServiceBundle, Depends(get_monitoring_services)]
"""FastAPI dependency type that injects the holdings monitoring service bundle."""


class MonitoringEvaluateRequest(BaseModel):
    """Request body for deterministic position monitoring evaluation.

    Attributes:
        portfolio_id: Identifier of the portfolio that owns the position.
        current_price: Optional current market price of the position.
        evidence_refs: Optional list of evidence references influencing the
            evaluation. Defaults to an empty list.
        model_rank_delta: Optional change in model ranking since entry.
        industry_exposure: Optional current industry exposure factor.
        strategy_failure: Whether the underlying strategy has failed. Defaults
            to ``False``.
        upcoming_event_at: Optional timestamp of an upcoming catalyst event.
        decision_at: Optional timestamp that anchors the evaluation.
    """

    portfolio_id: str = Field(min_length=1)
    current_price: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    model_rank_delta: float | None = None
    industry_exposure: float | None = None
    strategy_failure: bool = False
    upcoming_event_at: datetime | None = None
    decision_at: datetime | None = None


class ReviewCreate(BaseModel):
    """Request body for appending a position review record.

    Attributes:
        portfolio_id: Identifier of the portfolio that owns the position.
        alert_id: Optional identifier of the alert being reviewed.
        decision: Review decision chosen by the operator.
        rationale: Human-readable explanation for the decision.
        action_taken_at: Optional timestamp when the review action was taken.
    """

    portfolio_id: str = Field(min_length=1)
    alert_id: str | None = None
    decision: ReviewDecision
    rationale: str = Field(min_length=1)
    action_taken_at: datetime | None = None


def _not_found(exc: KeyError) -> HTTPException:
    """Convert a ``KeyError`` into an HTTP 404 exception.

    Args:
        exc: The original key error, typically raised when a portfolio or
            position identifier is not found.

    Returns:
        HTTPException: A 404 ``HTTPException`` carrying the original message.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/positions/{position_id}/monitoring/evaluate",
    response_model=PositionMonitoringSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def evaluate_position_monitoring(
    position_id: str,
    request: MonitoringEvaluateRequest,
    services: Services,
) -> PositionMonitoringSnapshot:
    """Evaluate a position using deterministic monitoring rules.

    Args:
        position_id: Unique identifier of the position to evaluate.
        request: Validated monitoring evaluation request.
        services: Monitoring service bundle used to run the evaluation.

    Returns:
        PositionMonitoringSnapshot: Snapshot of the position monitoring state
        after evaluation.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found.
    """
    try:
        return services.monitoring.evaluate_position_by_id(
            portfolio_id=request.portfolio_id,
            position_id=position_id,
            current_price=request.current_price,
            evidence_refs=request.evidence_refs,
            model_rank_delta=request.model_rank_delta,
            industry_exposure=request.industry_exposure,
            strategy_failure=request.strategy_failure,
            upcoming_event_at=request.upcoming_event_at,
            decision_at=request.decision_at,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/positions/{position_id}/alerts", response_model=list[AlertEvent])
def get_position_alerts(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[AlertEvent]:
    """Return append-only alert events for a position.

    Args:
        position_id: Unique identifier of the position.
        services: Monitoring service bundle used to load alerts.
        portfolio_id: Unique identifier of the portfolio, supplied as a query
            parameter.

    Returns:
        list[AlertEvent]: Alert events for the position.
    """
    return services.monitoring.list_alerts(portfolio_id, position_id)


@router.post(
    "/positions/{position_id}/reviews",
    response_model=PositionReviewRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_position_review(
    position_id: str,
    request: ReviewCreate,
    services: Services,
) -> PositionReviewRecord:
    """Append a manual review for a position.

    Args:
        position_id: Unique identifier of the position being reviewed.
        request: Validated review creation request.
        services: Monitoring service bundle used to persist the review.

    Returns:
        PositionReviewRecord: The newly created review record.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found.
    """
    try:
        return services.monitoring.record_review(
            portfolio_id=request.portfolio_id,
            position_id=position_id,
            alert_id=request.alert_id,
            decision=request.decision,
            rationale=request.rationale,
            action_taken_at=request.action_taken_at,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/positions/{position_id}/history",
    response_model=list[OperationHistoryEntry],
)
def get_position_history(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[OperationHistoryEntry]:
    """Return unified trade/alert/review operation history for a position.

    Args:
        position_id: Unique identifier of the position.
        services: Monitoring service bundle used to build the history.
        portfolio_id: Unique identifier of the portfolio, supplied as a query
            parameter.

    Returns:
        list[OperationHistoryEntry]: Unified operation history for the position.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found.
    """
    try:
        return services.monitoring.get_operation_history(
            portfolio_id=portfolio_id,
            position_id=position_id,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/positions/{position_id}/behavior-metrics",
    response_model=list[BehaviorMetric],
)
def get_position_behavior_metrics(
    position_id: str,
    services: Services,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> list[BehaviorMetric]:
    """Return action-latency metrics derived from alert and review records.

    Args:
        position_id: Unique identifier of the position.
        services: Monitoring service bundle used to compute metrics.
        portfolio_id: Unique identifier of the portfolio, supplied as a query
            parameter.

    Returns:
        list[BehaviorMetric]: Behaviour metrics for the position.
    """
    return services.monitoring.get_behavior_metrics(portfolio_id, position_id)
