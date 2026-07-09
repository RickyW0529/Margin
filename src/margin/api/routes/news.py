"""News refresh API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import (
    get_agentic_news_service,
    get_news_service,
    require_idempotency_key,
    require_local_admin,
)
from margin.news.agentic_acquisition import AgenticNewsAcquisitionService
from margin.news.models import NewsTarget, TargetTriggerType
from margin.news.service import NewsService

router = APIRouter(prefix="/api/v1/news", tags=["news"])


class NewsTargetRequest(BaseModel):
    """Request DTO for one news refresh target.."""

    model_config = ConfigDict(extra="forbid")

    security_id: str = Field(min_length=1, max_length=32)
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    trigger_type: TargetTriggerType
    priority: int = Field(ge=0, le=1000)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    industry_terms: tuple[str, ...] = Field(default_factory=tuple)


class NewsRefreshRequest(BaseModel):
    """Request body for starting a target-driven news refresh.."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    quant_run_id: str = Field(min_length=1, max_length=64)
    decision_at: datetime
    targets: list[NewsTargetRequest]


class NewsRefreshResponse(BaseModel):
    """Accepted refresh response.."""

    run_id: str
    status: str
    target_count: int


class NewsRunStatusResponse(BaseModel):
    """Refresh run reconciliation response.."""

    run_id: str
    status: str
    target_count: int
    pending_count: int
    claimed_count: int
    retry_count: int
    completed_count: int
    failed_final_count: int
    error_summary: dict[str, object]


class AgenticNewsRefreshRequest(BaseModel):
    """Request body for starting agentic news acquisition from a quant run.."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    quant_run_id: str = Field(min_length=1, max_length=64)
    decision_at: datetime
    include_near_threshold: bool = False
    max_workers: int = Field(default=4, ge=1, le=16)


class AgenticNewsRefreshResponse(BaseModel):
    """Accepted agentic refresh response.."""

    run_id: str
    status: str
    target_count: int
    include_near_threshold: bool


@router.post(
    "/refresh",
    response_model=NewsRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_news_refresh(
    request: NewsRefreshRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
    service: Annotated[NewsService, Depends(get_news_service)],
) -> NewsRefreshResponse:
    """Start a target-driven news refresh for the provided quant-selected companies.

    Args:
        request: NewsRefreshRequest: .
        idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .
        service: Annotated[NewsService, Depends(get_news_service)]: .

    Returns:
        NewsRefreshResponse: .
    """
    targets = [
        NewsTarget(
            scope_version_id=request.scope_version_id,
            quant_run_id=request.quant_run_id,
            security_id=item.security_id,
            symbol=item.symbol,
            name=item.name,
            trigger_type=item.trigger_type,
            decision_at=request.decision_at,
            priority=item.priority,
            aliases=item.aliases,
            industry_terms=item.industry_terms,
        )
        for item in request.targets
    ]
    run = service.start_refresh(
        scope_version_id=request.scope_version_id,
        quant_run_id=request.quant_run_id,
        decision_at=request.decision_at,
        targets=targets,
        idempotency_key=idempotency_key,
    )
    return NewsRefreshResponse(
        run_id=run.run_id,
        status=run.status.value,
        target_count=run.target_count,
    )


@router.post(
    "/agentic-refresh",
    response_model=AgenticNewsRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_agentic_news_refresh(
    request: AgenticNewsRefreshRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
    service: Annotated[
        AgenticNewsAcquisitionService,
        Depends(get_agentic_news_service),
    ],
) -> AgenticNewsRefreshResponse:
    """Start agentic news acquisition for a quant run.

    Args:
        request: AgenticNewsRefreshRequest: .
        idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .
        service: Annotated[AgenticNewsAcquisitionService, Depends(get_agentic_news_service)]: .

    Returns:
        AgenticNewsRefreshResponse: .
    """
    run = service.run_for_quant_run(
        scope_version_id=request.scope_version_id,
        quant_run_id=request.quant_run_id,
        decision_at=request.decision_at,
        include_near_threshold=request.include_near_threshold,
        max_workers=request.max_workers,
        idempotency_key=idempotency_key,
    )
    return AgenticNewsRefreshResponse(
        run_id=run.run_id,
        status=run.status.value,
        target_count=run.target_count,
        include_near_threshold=run.include_near_threshold,
    )


@router.get("/runs/{run_id}", response_model=NewsRunStatusResponse)
def get_news_refresh_status(
    run_id: str,
    service: Annotated[NewsService, Depends(get_news_service)],
) -> NewsRunStatusResponse:
    """Return target reconciliation and provider wait/failure details.

    Args:
        run_id: str: .
        service: Annotated[NewsService, Depends(get_news_service)]: .

    Returns:
        NewsRunStatusResponse: .
    """
    try:
        run = service.get_run_status(run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="news refresh run not found",
        ) from exc
    return NewsRunStatusResponse(**run.model_dump())
