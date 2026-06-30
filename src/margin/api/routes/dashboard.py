"""Research candidate dashboard API routes for the Margin API.

This module implements the REST surface for the v0.2 research candidate
dashboard, including paginated candidates, item detail aggregates, read-only
Copilot, feedback, provider status, and nightly run job records.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from margin.api.dependencies import get_dashboard_services
from margin.dashboard.models import (
    DashboardFilters,
    DashboardSort,
    FeedbackRecord,
    FeedbackType,
    JobRun,
    ProviderStatus,
    ReadOnlyCopilotResponse,
    ResearchCandidateListResponse,
    ResearchItemDetailV2,
)
from margin.dashboard.service import DashboardServiceBundle

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
"""APIRouter exposing dashboard-related endpoints under ``/api/v1``."""

Services = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]
"""FastAPI dependency type that injects the dashboard service bundle."""


class FeedbackCreate(BaseModel):
    """Request body for recording feedback on a research item.

    Attributes:
        feedback_type: Kind of feedback being recorded. Defaults to ``COMMENT``.
        comment: Free-text comment attached to the feedback.
    """

    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""


class CopilotRequest(BaseModel):
    """Read-only dashboard Copilot request.

    Attributes:
        scope_version_id: Identifier of the frozen research scope.
        message: User question text (1-2000 characters).
        universe: Universe code filter. Defaults to ``ALL_A``.
    """

    scope_version_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    universe: str = "ALL_A"


@router.get("/research", response_model=ResearchCandidateListResponse)
def list_research_candidates_v2(
    services: Services,
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
        services: Dashboard service bundle used to query candidates.
        scope_version_id: Identifier of the frozen research scope.
        universe: Universe code filter.
        limit: Maximum number of candidates to return.
        cursor: Optional pagination cursor from a previous response.
        screening_status: Optional screening status filter.
        data_status: Optional data status filter.
        review_required: Optional review-required filter.
        assessment_freshness: Optional assessment freshness filter.
        query: Optional free-text search query.
        sort_field: Field to sort by.
        sort_direction: Sort direction (``asc`` or ``desc``).

    Returns:
        ResearchCandidateListResponse containing one page of candidates.
    """
    return services.query.list_research_candidates_v2(
        scope_version_id=scope_version_id,
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
        item_id: Unique identifier of the research item.
        services: Dashboard service bundle used to load the detail.

    Returns:
        ResearchItemDetailV2 for the requested item, or a 404 JSONResponse
        if the item cannot be found.
    """
    try:
        return services.query.get_item_detail_v2(item_id)
    except KeyError:
        return _item_not_found(item_id)


@router.post("/research/copilot", response_model=ReadOnlyCopilotResponse)
def research_read_only_copilot(
    request: CopilotRequest,
    services: Services,
) -> ReadOnlyCopilotResponse | JSONResponse:
    """Answer dashboard questions using only read-only BFF data.

    Mutating intents (refresh, rerun, save, trade) are rejected with a 403
    response. Otherwise, the top PASS candidates are listed as the answer.

    Args:
        request: Validated Copilot request containing scope, message, and
            universe.
        services: Dashboard service bundle used to query candidates.

    Returns:
        ReadOnlyCopilotResponse with a read-only answer, or a 403 JSONResponse
        when a mutating intent is detected.
    """
    if _has_mutating_intent(request.message):
        message = (
            "Copilot is read-only and cannot refresh, rerun, mutate settings, "
            "or trade."
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "code": "copilot_read_only",
                "message": message,
                "trace_id": request.scope_version_id,
                "retryable": False,
            },
        )
    candidates = services.query.list_research_candidates_v2(
        scope_version_id=request.scope_version_id,
        universe_code=request.universe,
        filters=DashboardFilters(screening_status="pass"),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=None,
        limit=5,
    )
    symbols = [item.symbol for item in candidates.items]
    answer = (
        "当前可继续看的候选来自研究候选只读列表："
        + ("、".join(symbols) if symbols else "暂无 PASS 候选")
        + "。该回答不触发同步、新闻刷新、AI 复核或交易动作。"
    )
    return ReadOnlyCopilotResponse(
        answer=answer,
        references=(
            {
                "api": "GET /api/v1/research",
                "scope_version_id": request.scope_version_id,
                "universe": request.universe,
            },
        ),
    )


def _item_not_found(item_id: str) -> JSONResponse:
    """Return a v0.2 structured item-not-found error."""
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
    """Convert a ``KeyError`` into a simple HTTP 404 exception."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _has_mutating_intent(message: str) -> bool:
    """Detect write/refresh/trading intents and fail closed."""
    normalized = message.lower()
    mutating_keywords = (
        "重新跑",
        "重跑",
        "刷新",
        "同步",
        "搜索新闻",
        "websearch",
        "保存",
        "修改",
        "配置",
        "激活",
        "测试 provider",
        "retry",
        "rerun",
        "refresh",
        "sync",
        "save",
        "activate",
        "buy",
        "sell",
        "下单",
        "买入",
        "卖出",
    )
    return any(keyword in normalized for keyword in mutating_keywords)


@router.post(
    "/research-items/{item_id}/feedback",
    response_model=FeedbackRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_research_item_feedback(
    item_id: str,
    request: FeedbackCreate,
    services: Services,
) -> FeedbackRecord:
    """Append feedback for a research item.

    Args:
        item_id: Unique identifier of the research item.
        request: Validated feedback creation request.
        services: Dashboard service bundle used to record feedback.

    Returns:
        FeedbackRecord: The newly created feedback record.

    Raises:
        HTTPException: 404 if the item cannot be found.
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
        services: Dashboard service bundle that owns provider status.

    Returns:
        list[ProviderStatus]: Health status for each configured or missing
        provider.
    """
    return services.providers.list_status()


@router.get("/jobs/{job_run_id}", response_model=JobRun)
def get_job_run(job_run_id: str, services: Services) -> JobRun:
    """Return a dashboard job record.

    Args:
        job_run_id: Unique identifier of the job run.
        services: Dashboard service bundle used to load the job record.

    Returns:
        JobRun: The requested job run record.

    Raises:
        HTTPException: 404 if the job run cannot be found.
    """
    try:
        return services.jobs.get_job(job_run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
