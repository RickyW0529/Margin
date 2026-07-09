"""Research candidate dashboard API routes for the Margin API.

This module implements the REST surface for the v0.2 research candidate
dashboard, including paginated candidates, item detail aggregates, feedback,
provider status, and nightly run job records.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from margin.api.dependencies import (
    get_dashboard_services,
    get_strategy_service,
    require_idempotency_key,
)
from margin.dashboard.models import (
    DashboardFilters,
    DashboardSort,
    FeedbackRecord,
    FeedbackType,
    JobRun,
    ProviderStatus,
    ResearchCandidateListResponse,
    ResearchItemDetailV2,
)
from margin.dashboard.service import DashboardServiceBundle
from margin.strategy.service import StrategyService

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
"""APIRouter exposing dashboard-related endpoints under ``/api/v1``."""

Services = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]
"""FastAPI dependency type that injects the dashboard service bundle."""
StrategyServices = Annotated[StrategyService, Depends(get_strategy_service)]
"""FastAPI dependency type that injects the strategy service."""


class FeedbackCreate(BaseModel):
    """Request body for recording feedback on a research item.."""

    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""


@router.get("/research", response_model=ResearchCandidateListResponse)
def list_research_candidates_v2(
    services: Services,
    strategy_service: StrategyServices,
    scope_version_id: str,
    universe: Annotated[str, Query(alias="universe")] = "ALL_A",
    limit: int = 50,
    cursor: str | None = None,
    screening_status: str | None = None,
    data_status: str | None = None,
    review_required: bool | None = None,
    assessment_freshness: str | None = None,
    query: str | None = None,
    sort_field: str = "final_score",
    sort_direction: str = "desc",
) -> ResearchCandidateListResponse:
    """Return one v0.2 server-paginated research candidate page.

    Args:
        services: Services: .
        strategy_service: StrategyServices: .
        scope_version_id: str: .
        universe: Annotated[str, Query(alias='universe')]: .
        limit: int: .
        cursor: str | None: .
        screening_status: str | None: .
        data_status: str | None: .
        review_required: bool | None: .
        assessment_freshness: str | None: .
        query: str | None: .
        sort_field: str: .
        sort_direction: str: .

    Returns:
        ResearchCandidateListResponse: .
    """
    resolved_scope_version_id = _resolve_scope_alias(
        scope_version_id,
        strategy_service=strategy_service,
    )
    return services.query.list_research_candidates_v2(
        scope_version_id=resolved_scope_version_id,
        universe_code=universe,
        filters=DashboardFilters(
            screening_status=screening_status,
            data_status=data_status,
            review_required=review_required,
            assessment_freshness=assessment_freshness,
            query=query,
        ),
        sort=DashboardSort(field=sort_field, direction=sort_direction),
        cursor=cursor,
        limit=limit,
    )


@router.get("/research/items/{item_id}", response_model=ResearchItemDetailV2)
def get_research_item_detail_v2(
    item_id: str,
    services: Services,
) -> ResearchItemDetailV2 | JSONResponse:
    """Return v0.2 company detail aggregate for one research item.

    Args:
        item_id: str: .
        services: Services: .

    Returns:
        ResearchItemDetailV2 | JSONResponse: .
    """
    try:
        return services.query.get_item_detail_v2(item_id)
    except KeyError:
        return _item_not_found(item_id)


def _resolve_scope_alias(
    scope_version_id: str,
    *,
    strategy_service: StrategyService,
    owner_id: str = "local-admin",
) -> str:
    """Resolve user-facing scope aliases to persisted scope version IDs.

    Args:
        scope_version_id: str: .
        strategy_service: StrategyService: .
        owner_id: str: .

    Returns:
        str: .
    """
    if scope_version_id != "scope-current":
        return scope_version_id
    try:
        scope = strategy_service.ensure_current_research_scope(owner_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_configured",
                "message": "active research scope not found",
            },
        ) from exc
    return str(scope.version_id)


def _item_not_found(item_id: str) -> JSONResponse:
    """Return a v0.2 structured item-not-found error.

    Args:
        item_id: str: .

    Returns:
        JSONResponse: .
    """
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "code": "item_not_found",
            "message": "research item not found",
            "trace_id": item_id,
            "retryable": False,
        },
    )


def _not_found(exc: KeyError) -> HTTPException:
    """Convert a ``KeyError`` into a simple HTTP 404 exception.

    Args:
        exc: KeyError: .

    Returns:
        HTTPException: .
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/research-items/{item_id}/feedback",
    response_model=FeedbackRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_research_item_feedback(
    item_id: str,
    request: FeedbackCreate,
    services: Services,
    _idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> FeedbackRecord:
    """Append feedback for a research item.

    Args:
        item_id: str: .
        request: FeedbackCreate: .
        services: Services: .
        _idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .

    Returns:
        FeedbackRecord: .
    """
    try:
        return services.feedback.record_feedback(
            item_id,
            request.feedback_type,
            request.comment,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/provider-status", response_model=list[ProviderStatus])
def get_provider_status(services: Services) -> list[ProviderStatus]:
    """Return provider health status used by the dashboard.

    Args:
        services: Services: .

    Returns:
        list[ProviderStatus]: .
    """
    return services.providers.list_status()


@router.get("/jobs/{job_run_id}", response_model=JobRun)
def get_job_run(job_run_id: str, services: Services) -> JobRun:
    """Return a dashboard job record.

    Args:
        job_run_id: str: .
        services: Services: .

    Returns:
        JobRun: .
    """
    try:
        return services.jobs.get_job(job_run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
