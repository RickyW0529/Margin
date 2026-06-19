"""Holdings monitoring API routes for module 09."""

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

Services = Annotated[MonitoringServiceBundle, Depends(get_monitoring_services)]


class MonitoringEvaluateRequest(BaseModel):
    """Request body for deterministic position monitoring evaluation."""

    portfolio_id: str = Field(min_length=1)
    current_price: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    model_rank_delta: float | None = None
    industry_exposure: float | None = None
    strategy_failure: bool = False
    upcoming_event_at: datetime | None = None
    decision_at: datetime | None = None


class ReviewCreate(BaseModel):
    """Request body for appending a position review record."""

    portfolio_id: str = Field(min_length=1)
    alert_id: str | None = None
    decision: ReviewDecision
    rationale: str = Field(min_length=1)
    action_taken_at: datetime | None = None


def _not_found(exc: KeyError) -> HTTPException:
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
    """Evaluate a position using deterministic monitoring rules."""
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
    """Return append-only alert events for a position."""
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
    """Append a manual review for a position alert."""
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
    """Return unified trade/alert/review operation history for a position."""
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
    """Return action-latency metrics derived from alert/review records."""
    return services.monitoring.get_behavior_metrics(portfolio_id, position_id)
