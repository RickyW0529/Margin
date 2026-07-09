"""Backfill campaign control-plane API routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import (
    get_backfill_application_service,
    require_idempotency_key,
    require_local_admin,
)
from margin.data.backfill.campaign import BackfillCampaign
from margin.data.backfill.planner import BackfillPartition
from margin.data.backfill.publisher import BackfillPublishResult
from margin.data.backfill.quality import BackfillQualityReport
from margin.data.backfill.service import BackfillApplicationService, BackfillRunSummary

router = APIRouter(prefix="/api/v1", tags=["backfill"])

BackfillService = Annotated[
    BackfillApplicationService,
    Depends(get_backfill_application_service),
]


class CreateBackfillCampaignRequest(BaseModel):
    """CreateBackfillCampaignRequest.."""

    model_config = ConfigDict(extra="forbid")

    campaign_name: str = Field(default="full_market_20y", min_length=1, max_length=96)
    years: int = Field(default=20, ge=1)
    start_date: date = date(2006, 1, 1)
    end_date: date | Literal["auto"] = "auto"
    providers: tuple[str, ...] = ("tushare", "akshare")
    mode: Literal["dry_run", "live"] = "dry_run"


class BackfillCampaignResponse(BaseModel):
    """BackfillCampaignResponse.."""

    campaign: BackfillCampaign
    endpoint_count: int
    partition_count: int
    quality_report_available: bool


class BackfillPartitionListResponse(BaseModel):
    """BackfillPartitionListResponse.."""

    items: list[BackfillPartition]


@router.post(
    "/backfill-campaigns",
    response_model=BackfillCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_backfill_campaign(
    request: CreateBackfillCampaignRequest,
    service: BackfillService,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> BackfillCampaignResponse:
    """Create backfill campaign.

    Args:
        request: CreateBackfillCampaignRequest: .
        service: BackfillService: .
        idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .

    Returns:
        BackfillCampaignResponse: .
    """
    summary = service.create_campaign(
        campaign_name=request.campaign_name,
        providers=request.providers,
        years=request.years,
        start_date=request.start_date,
        end_date=request.end_date,
        mode=request.mode,
        idempotency_key=idempotency_key,
    )
    return BackfillCampaignResponse(**summary.model_dump(mode="python"))


@router.get(
    "/backfill-campaigns/{campaign_id}",
    response_model=BackfillCampaignResponse,
)
def get_backfill_campaign(
    campaign_id: str,
    service: BackfillService,
) -> BackfillCampaignResponse:
    """Get backfill campaign.

    Args:
        campaign_id: str: .
        service: BackfillService: .

    Returns:
        BackfillCampaignResponse: .
    """
    try:
        summary = service.get_campaign(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc
    return BackfillCampaignResponse(**summary.model_dump(mode="python"))


@router.get(
    "/backfill-campaigns/{campaign_id}/partitions",
    response_model=BackfillPartitionListResponse,
)
def list_backfill_partitions(
    campaign_id: str,
    service: BackfillService,
) -> BackfillPartitionListResponse:
    """List backfill partitions.

    Args:
        campaign_id: str: .
        service: BackfillService: .

    Returns:
        BackfillPartitionListResponse: .
    """
    try:
        partitions = service.list_partitions(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc
    return BackfillPartitionListResponse(items=list(partitions))


@router.post(
    "/backfill-campaigns/{campaign_id}/run",
    response_model=BackfillRunSummary,
)
def run_backfill_campaign(
    campaign_id: str,
    service: BackfillService,
    _idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> BackfillRunSummary:
    """Run backfill campaign.

    Args:
        campaign_id: str: .
        service: BackfillService: .
        _idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .

    Returns:
        BackfillRunSummary: .
    """
    try:
        return service.run_campaign(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc


@router.post(
    "/backfill-campaigns/{campaign_id}/verify",
    response_model=BackfillQualityReport,
)
def verify_backfill_campaign(
    campaign_id: str,
    service: BackfillService,
    _idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> BackfillQualityReport:
    """Verify backfill campaign.

    Args:
        campaign_id: str: .
        service: BackfillService: .
        _idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .

    Returns:
        BackfillQualityReport: .
    """
    try:
        return service.verify_campaign(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc


@router.get(
    "/backfill-campaigns/{campaign_id}/quality-report",
    response_model=BackfillQualityReport,
)
def get_backfill_quality_report(
    campaign_id: str,
    service: BackfillService,
) -> BackfillQualityReport:
    """Get backfill quality report.

    Args:
        campaign_id: str: .
        service: BackfillService: .

    Returns:
        BackfillQualityReport: .
    """
    try:
        report = service.get_quality_report(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "backfill_quality_report_not_found",
                "message": "backfill quality report not found",
            },
        )
    return report


@router.post(
    "/backfill-campaigns/{campaign_id}/publish",
    response_model=BackfillPublishResult,
)
def publish_backfill_campaign(
    campaign_id: str,
    service: BackfillService,
    _idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> BackfillPublishResult:
    """Publish backfill campaign.

    Args:
        campaign_id: str: .
        service: BackfillService: .
        _idempotency_key: Annotated[str, Depends(require_idempotency_key)]: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .

    Returns:
        BackfillPublishResult: .
    """
    try:
        return service.publish_campaign(campaign_id)
    except KeyError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "backfill_publish_blocked",
                "message": str(exc),
            },
        ) from exc


def _not_found() -> HTTPException:
    """Not found.

    Returns:
        HTTPException: .
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "backfill_campaign_not_found",
            "message": "backfill campaign not found",
        },
    )
