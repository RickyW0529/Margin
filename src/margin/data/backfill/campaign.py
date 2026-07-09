"""Deterministic campaign models for the 20-year backfill control plane."""

from __future__ import annotations

import re
from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TWENTY_YEAR_BACKFILL_START_DATE = date(2006, 1, 1)


class BackfillCampaignStatus(StrEnum):
    """BackfillCampaignStatus.."""

    PLANNED = "planned"
    RUNNING = "running"
    VERIFIED = "verified"
    PUBLISHED = "published"
    BLOCKED = "blocked"
    FAILED = "failed"


class BackfillCampaign(BaseModel):
    """BackfillCampaign.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_id: str
    campaign_name: str
    years: int = Field(default=20, ge=1)
    start_date: date
    end_date: date
    providers: tuple[str, ...]
    status: BackfillCampaignStatus = BackfillCampaignStatus.PLANNED
    mode: Literal["dry_run", "live"] = "dry_run"

    @field_validator("providers")
    @classmethod
    def normalize_providers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize providers.

        Args:
            value: tuple[str, ...]: .

        Returns:
            tuple[str, ...]: .
        """
        normalized = tuple(provider.strip().lower() for provider in value if provider.strip())
        if not normalized:
            raise ValueError("at least one provider is required")
        return normalized


class BackfillCampaignService:
    """BackfillCampaignService.."""

    def __init__(self, *, today: date | None = None) -> None:
        """Init .

        Args:
            today: date | None: .

        Returns:
            None: .
        """
        self._today = today or date.today()

    def init_campaign(
        self,
        *,
        campaign_name: str,
        providers: tuple[str, ...],
        years: int = 20,
        start_date: date | str | None = None,
        end_date: date | str = "auto",
        mode: Literal["dry_run", "live"] = "dry_run",
    ) -> BackfillCampaign:
        """Init campaign.

        Args:
            campaign_name: str: .
            providers: tuple[str, ...]: .
            years: int: .
            start_date: date | str | None: .
            end_date: date | str: .
            mode: Literal['dry_run', 'live']: .

        Returns:
            BackfillCampaign: .
        """
        resolved_start = _parse_date(start_date) if start_date else TWENTY_YEAR_BACKFILL_START_DATE
        if years == 20 and resolved_start != TWENTY_YEAR_BACKFILL_START_DATE:
            raise ValueError("20-year campaign must start at 2006-01-01")
        resolved_end = (
            self.latest_completed_trading_day() if end_date == "auto" else _parse_date(end_date)
        )
        if resolved_end < resolved_start:
            raise ValueError("end_date must be on or after start_date")
        slug = _slug(campaign_name)
        campaign_id = f"bf_{slug}_{self._today:%Y%m%d}"
        return BackfillCampaign(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            years=years,
            start_date=resolved_start,
            end_date=resolved_end,
            providers=providers,
            mode=mode,
        )

    def latest_completed_trading_day(self) -> date:
        """Latest completed trading day.

        Returns:
            date: .
        """
        return self._today - timedelta(days=1)


def _parse_date(value: date | str) -> date:
    """Parse date.

    Args:
        value: date | str: .

    Returns:
        date: .
    """
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _slug(value: str) -> str:
    """Slug.

    Args:
        value: str: .

    Returns:
        str: .
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "backfill"
