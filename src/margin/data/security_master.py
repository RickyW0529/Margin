"""Security master and provider identifier domain records."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class SecurityMasterRecord(BaseModel):
    """Bitemporal security master record."""

    security_id: str
    symbol: str
    name: str
    exchange: str
    listed_at: date | None = None
    delisted_at: date | None = None
    security_type: str = "stock"
    system_from: datetime
    system_to: datetime | None = None
    raw_lineage_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}

    @field_validator("system_from", "system_to")
    @classmethod
    def normalize_system_time(cls, value: datetime | None) -> datetime | None:
        """Normalize system-time fields to UTC."""
        return ensure_utc(value) if value is not None else None


class SecurityProviderIdentifier(BaseModel):
    """Provider-specific identifier for a security with PIT validity."""

    security_id: str
    provider: str
    provider_symbol: str
    valid_from: date
    valid_to: date | None = None
    system_from: datetime
    system_to: datetime | None = None

    model_config = {"frozen": True}

    @field_validator("system_from", "system_to")
    @classmethod
    def normalize_system_time(cls, value: datetime | None) -> datetime | None:
        """Normalize system-time fields to UTC."""
        return ensure_utc(value) if value is not None else None
