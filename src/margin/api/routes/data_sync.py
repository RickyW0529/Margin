"""Manual data sync trigger API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from margin.api.dependencies import get_data_warehouse_stack
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_models import DataSyncRequest

router = APIRouter(prefix="/api/v1", tags=["data-sync"])
"""APIRouter exposing manual data sync trigger endpoints under ``/api/v1``."""

Stack = Annotated[DataWarehouseIngestionStack, Depends(get_data_warehouse_stack)]
"""FastAPI dependency type that injects the data warehouse ingestion stack."""


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


@router.post(
    "/data-sync",
    response_model=DataSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_data_sync(
    request: DataSyncTriggerRequest,
    stack: Stack,
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
    sync_request = DataSyncRequest(
        provider=request.provider,
        endpoint_codes=request.endpoint_codes,
        requested_by=request.requested_by,
        backfill_start=request.backfill_start,
        backfill_end=request.backfill_end,
        force_full_refresh=request.force_full_refresh,
    )
    run = stack.create_sync_run(sync_request)
    return DataSyncResponse(
        sync_run_id=run.run_id,
        status=run.status.value,
    )
