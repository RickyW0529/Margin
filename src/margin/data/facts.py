"""Standardized provider facts used by canonical data resolution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class StandardizedIndicatorFact(BaseModel):
    """Append-only canonical-indicator fact from one provider payload."""

    fact_id: str
    provider_code: str
    provider_fact_id: str
    endpoint_code: str
    security_id: str
    indicator_id: str
    indicator_version: str
    event_at: datetime
    available_at: datetime
    fetched_at: datetime
    published_at: datetime | None = None
    revised_at: datetime | None = None
    numeric_value: Decimal | None = None
    text_value: str | None = None
    json_value: dict[str, Any] | None = None
    unit: str | None = None
    quality_score: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    mapping_version: str
    raw_snapshot_id: str
    lineage: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("event_at", "available_at", "fetched_at", "published_at", "revised_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize fact timestamps to UTC."""
        return ensure_utc(value) if value is not None else None

    @property
    def provider(self) -> str:
        """Alias matching warehouse row naming."""
        return self.provider_code

    def is_available_at(self, decision_at: datetime) -> bool:
        """Return whether the fact is point-in-time legal at ``decision_at``."""
        return self.available_at <= ensure_utc(decision_at)
