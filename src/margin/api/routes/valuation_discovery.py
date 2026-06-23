"""Valuation discovery API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import (
    get_valuation_discovery_service_for_api,
    require_idempotency_key,
    require_local_admin,
)
from margin.valuation_discovery.service import ValuationDiscoveryService

router = APIRouter(prefix="/api/v1/valuation-discovery", tags=["valuation-discovery"])


class StartRefreshRequest(BaseModel):
    """Request body for starting a valuation discovery refresh."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    decision_at: datetime


class StartRefreshResponse(BaseModel):
    """Accepted refresh response."""

    run_id: str
    status: str
    http_status: int


class RefreshStatusResponse(BaseModel):
    """Valuation discovery refresh run status."""

    run_id: str
    state: str
    scope_version_id: str
    steps: list[dict[str, Any]]


class RefreshSummaryResponse(BaseModel):
    """One refresh run row in the list view."""

    run_id: str
    state: str
    scope_version_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RefreshListResponse(BaseModel):
    """Paginated refresh run list response."""

    items: list[RefreshSummaryResponse]
    next_cursor: str | None
    page_size: int


TERMINAL_STATES = frozenset(
    {"succeeded", "failed_final", "cancelled", "skipped"}
)


def _has_next(items: list, limit: int) -> str | None:
    """Return a cursor for the last item when more rows may exist."""
    if len(items) >= limit and items:
        return items[-1].run_id
    return None


@router.post(
    "/refreshes",
    response_model=StartRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_refresh(
    request: StartRefreshRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
) -> StartRefreshResponse:
    """Start a valuation discovery refresh."""
    response = service.start_refresh(
        scope_version_id=request.scope_version_id,
        decision_at=request.decision_at,
        idempotency_key=idempotency_key,
    )
    return StartRefreshResponse(
        run_id=response.run_id,
        status=response.status,
        http_status=response.http_status,
    )


@router.get(
    "/runs",
    response_model=RefreshListResponse,
)
def list_refresh_runs(
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
    scope_version_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RefreshListResponse:
    """List recent valuation-discovery refresh runs, newest first.

    Args:
        scope_version_id: Optional scope-version filter.
        state: Optional run-state filter.
        limit: Maximum number of runs to return (1..200).
        service: Valuation discovery service used to list runs.

    Returns:
        RefreshListResponse: A page of runs plus a cursor for the next page.
    """
    summaries = service.list_refreshes(
        scope_version_id=scope_version_id,
        state=state,
        limit=limit + 1,
    )
    items = summaries[:limit]
    return RefreshListResponse(
        items=[
            RefreshSummaryResponse(
                run_id=item.run_id,
                state=item.state,
                scope_version_id=item.scope_version_id,
                created_at=item.created_at,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in items
        ],
        next_cursor=items[-1].run_id if len(summaries) > limit and items else None,
        page_size=len(items),
    )


@router.get(
    "/runs/{run_id}",
    response_model=RefreshStatusResponse,
)
def get_refresh_status(
    run_id: str,
    service: Annotated[
        ValuationDiscoveryService,
        Depends(get_valuation_discovery_service_for_api),
    ],
) -> RefreshStatusResponse:
    """Return the status of a valuation discovery refresh run.

    Args:
        run_id: Unique identifier of the refresh run to inspect.
        service: Valuation discovery service used to load run status.

    Returns:
        RefreshStatusResponse: The run's current state together with the
        latest event for each orchestration step.

    Raises:
        HTTPException: 404 if the run cannot be found.
    """
    status_dto = service.get_refresh_status(run_id)
    if status_dto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"refresh run '{run_id}' not found",
        )
    return RefreshStatusResponse(
        run_id=status_dto.run_id,
        state=status_dto.state,
        scope_version_id=status_dto.scope_version_id,
        steps=status_dto.steps,
    )
