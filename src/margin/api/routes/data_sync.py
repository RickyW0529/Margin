"""Manual data sync trigger API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import (
    get_data_policy_service,
    get_data_warehouse_stack,
    require_idempotency_key,
    require_local_admin,
)
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.policy import (
    DataAcquisitionPolicyService,
    DataAcquisitionPolicyVersion,
)
from margin.data.sync_models import DataSyncRequest

router = APIRouter(prefix="/api/v1", tags=["data-sync"])
"""APIRouter exposing manual data sync trigger endpoints under ``/api/v1``."""

Stack = Annotated[DataWarehouseIngestionStack, Depends(get_data_warehouse_stack)]
"""FastAPI dependency type that injects the data warehouse ingestion stack."""

PolicyService = Annotated[
    DataAcquisitionPolicyService,
    Depends(get_data_policy_service),
]


class DataSyncTriggerRequest(BaseModel):
    """Request body for triggering a manual data sync run."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=64)
    endpoint_codes: tuple[str, ...] = Field(default_factory=tuple)
    requested_by: str = Field(default="manual-api", min_length=1, max_length=64)
    backfill_start: datetime | None = None
    backfill_end: datetime | None = None
    force_full_refresh: bool = False


class DataSyncResponse(BaseModel):
    """Manual data sync trigger response."""

    sync_run_id: str
    status: str


class CreateDataPolicyRequest(BaseModel):
    """Frontend request for a new immutable rolling-window policy."""

    model_config = ConfigDict(extra="forbid")

    rolling_window_months: int = Field(default=24, ge=12, le=60)
    revision_lookback_days: int = Field(default=30, ge=0, le=365)
    financial_comparison_years: int = Field(default=1, ge=1, le=3)


class DataPolicyResponse(BaseModel):
    """Safe policy response including a current window preview."""

    version_id: str
    owner_id: str
    rolling_window_months: int
    revision_lookback_days: int
    financial_comparison_years: int
    lifecycle: str
    config_hash: str
    created_at: datetime
    activated_at: datetime | None
    window_start: datetime
    window_end: datetime

    @classmethod
    def from_version(
        cls,
        version: DataAcquisitionPolicyVersion,
        *,
        now: datetime | None = None,
    ) -> DataPolicyResponse:
        """Render one immutable policy and its current rolling window."""
        observed_at = now or datetime.now().astimezone()
        window = version.window_for(observed_at)
        return cls(
            version_id=version.version_id,
            owner_id=version.owner_id,
            rolling_window_months=version.rolling_window_months,
            revision_lookback_days=version.revision_lookback_days,
            financial_comparison_years=version.financial_comparison_years,
            lifecycle=version.lifecycle.value,
            config_hash=version.config_hash,
            created_at=version.created_at,
            activated_at=version.activated_at,
            window_start=window.start,
            window_end=window.end,
        )


class DataPolicyListResponse(BaseModel):
    """List response consumed by the frontend Data Policy page."""

    active_version_id: str
    versions: list[DataPolicyResponse]


@router.get("/data-policies", response_model=DataPolicyListResponse)
def list_data_policies(service: PolicyService) -> DataPolicyListResponse:
    """List versions and identify the effective active/default policy."""
    active = service.get_active()
    versions = service.list_versions()
    if all(version.version_id != active.version_id for version in versions):
        versions = [active, *versions]
    return DataPolicyListResponse(
        active_version_id=active.version_id,
        versions=[DataPolicyResponse.from_version(version) for version in versions],
    )


@router.post(
    "/data-policies",
    response_model=DataPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_data_policy(
    request: CreateDataPolicyRequest,
    service: PolicyService,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> DataPolicyResponse:
    """Create an append-only draft policy from frontend settings."""
    version = service.create(
        rolling_window_months=request.rolling_window_months,
        revision_lookback_days=request.revision_lookback_days,
        financial_comparison_years=request.financial_comparison_years,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    return DataPolicyResponse.from_version(version)


@router.post(
    "/data-policies/{version_id}/activate",
    response_model=DataPolicyResponse,
)
def activate_data_policy(
    version_id: str,
    service: PolicyService,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> DataPolicyResponse:
    """Activate one policy version without running a synchronous backfill."""
    try:
        version = service.activate(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DataPolicyResponse.from_version(version)


@router.post(
    "/data-sync",
    response_model=DataSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_data_sync(
    request: DataSyncTriggerRequest,
    stack: Stack,
    policy_service: PolicyService,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> DataSyncResponse:
    """Trigger a manual data sync run.

    Creates a durable sync run in the ``pending`` state and returns its
    identifier. The run is executed asynchronously by data sync workers.

    Args:
        request: Validated sync trigger request describing the provider and
            optional backfill window.
        stack: Data warehouse ingestion stack used to persist the sync run.

    Returns:
        DataSyncResponse: The created sync run identifier together with its
        initial ``pending`` status.
    """
    policy = policy_service.get_active()
    window = policy.window_for(datetime.now().astimezone())
    requested_start = request.backfill_start or window.start
    requested_end = request.backfill_end or window.end
    effective_start = max(requested_start, window.start)
    effective_end = min(requested_end, window.end)
    if effective_start > effective_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="requested backfill range does not overlap the active data window",
        )
    sync_request = DataSyncRequest(
        provider=request.provider,
        endpoint_codes=request.endpoint_codes,
        requested_by=f"{request.requested_by}:{actor_id}",
        backfill_start=effective_start,
        backfill_end=effective_end,
        force_full_refresh=request.force_full_refresh,
        data_policy_version_id=policy.version_id,
        window_start=window.start,
        window_end=window.end,
        idempotency_key=idempotency_key,
    )
    run = stack.create_sync_run(sync_request)
    return DataSyncResponse(
        sync_run_id=run.run_id,
        status=run.status.value,
    )
