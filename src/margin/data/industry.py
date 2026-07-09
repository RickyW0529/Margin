"""Bitemporal industry membership resolution."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class IndustryMembership(BaseModel):
    """Industry membership with valid-time and system-time intervals.."""

    security_id: str
    taxonomy: str
    industry_code: str
    industry_name: str
    valid_from: date
    valid_to: date | None = None
    system_from: datetime
    system_to: datetime | None = None
    source: str
    quality: str
    raw_lineage_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}

    @field_validator("system_from", "system_to")
    @classmethod
    def normalize_system_time(cls, value: datetime | None) -> datetime | None:
        """Normalize system-time fields to UTC.

        Args:
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        return ensure_utc(value) if value is not None else None

    def is_visible_at(self, *, business_at: date, known_at: datetime) -> bool:
        """Return whether this membership is valid and known at the given times.

        Args:
            business_at: date: .
            known_at: datetime: .

        Returns:
            bool: .
        """
        normalized_known_at = ensure_utc(known_at)
        valid_time_match = self.valid_from <= business_at and (
            self.valid_to is None or business_at < self.valid_to
        )
        system_time_match = self.system_from <= normalized_known_at and (
            self.system_to is None or normalized_known_at < self.system_to
        )
        return valid_time_match and system_time_match


class BitemporalIndustryResolver:
    """Resolve industry membership by security, taxonomy, valid time, and system time.."""

    def __init__(self, memberships: list[IndustryMembership]) -> None:
        """Initialize the resolver.

        Args:
            memberships: list[IndustryMembership]: .

        Returns:
            None: .
        """
        self._memberships = tuple(memberships)

    def resolve(
        self,
        security_id: str,
        taxonomy: str,
        business_at: date,
        known_at: datetime,
    ) -> IndustryMembership:
        """Return the unique membership visible at the requested times.

        Args:
            security_id: str: .
            taxonomy: str: .
            business_at: date: .
            known_at: datetime: .

        Returns:
            IndustryMembership: .
        """
        matches = [
            membership
            for membership in self._memberships
            if membership.security_id == security_id
            and membership.taxonomy == taxonomy
            and membership.is_visible_at(business_at=business_at, known_at=known_at)
        ]
        if not matches:
            raise KeyError(
                "industry membership not found: "
                f"{security_id}/{taxonomy}/{business_at}/{known_at.isoformat()}"
            )
        matches.sort(key=lambda item: (item.system_from, item.valid_from), reverse=True)
        return matches[0]
