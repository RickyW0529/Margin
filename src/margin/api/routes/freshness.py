"""Data freshness status API."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from margin.data.freshness import DataDomain, FreshnessCalculator

router = APIRouter(prefix="/api/v1", tags=["freshness"])


class DataFreshnessItemResponse(BaseModel):
    """One data freshness state.."""

    domain: str
    as_of_date: date
    expected_at: datetime
    observed_at: datetime | None
    status: str
    lag_seconds: int | None


class DataFreshnessResponse(BaseModel):
    """Freshness status response.."""

    items: list[DataFreshnessItemResponse]


@router.get("/data-freshness", response_model=DataFreshnessResponse)
def get_data_freshness(
    domains: list[DataDomain] = Query(default=list(DataDomain)),
    now: datetime | None = None,
) -> DataFreshnessResponse:
    """Return deterministic freshness expectations for selected domains.

    Args:
        domains: list[DataDomain]: .
        now: datetime | None: .

    Returns:
        DataFreshnessResponse: .
    """
    observed_now = now or datetime.now(UTC)
    trading_days = {
        observed_now.date(),
        date.fromordinal(observed_now.date().toordinal() - 1),
        date.fromordinal(observed_now.date().toordinal() - 2),
    }
    calculator = FreshnessCalculator(trading_days=trading_days)
    return DataFreshnessResponse(
        items=[
            DataFreshnessItemResponse(
                **calculator.evaluate(
                    domain,
                    now=observed_now,
                    latest_observed_at=None,
                ).__dict__
            )
            for domain in domains
        ]
    )
