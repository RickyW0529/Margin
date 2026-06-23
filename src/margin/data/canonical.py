"""Canonical indicator value resolution across provider facts."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from margin.data.facts import StandardizedIndicatorFact
from margin.news.models import ensure_utc, utc_now


class CanonicalResolution(BaseModel):
    """Result of resolving provider facts for one indicator at one decision time."""

    security_id: str | None = None
    indicator_id: str | None = None
    decision_at: datetime
    status: str
    selected: StandardizedIndicatorFact | None = None
    candidates: tuple[StandardizedIndicatorFact, ...] = Field(default_factory=tuple)
    confidence: Decimal = Decimal("0")
    resolver_version: str = "canonical-resolver-v0.2.0"
    resolver_hash: str
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Normalize resolver timestamps to UTC."""
        return ensure_utc(value)


class CanonicalResolver:
    """Deterministically select a PIT-legal canonical fact while preserving candidates."""

    def __init__(
        self,
        *,
        resolver_version: str = "canonical-resolver-v0.2.0",
        provider_priority: tuple[str, ...] = ("tushare", "akshare"),
    ) -> None:
        """Initialize the instance."""
        self.resolver_version = resolver_version
        self.provider_priority = provider_priority

    def resolve(
        self,
        facts: list[StandardizedIndicatorFact],
        *,
        decision_at: datetime,
    ) -> CanonicalResolution:
        """Resolve available provider facts into one selected canonical value."""
        normalized_decision_at = ensure_utc(decision_at)
        available = tuple(
            sorted(
                (fact for fact in facts if fact.is_available_at(normalized_decision_at)),
                key=self._candidate_key,
            )
        )
        if not available:
            return CanonicalResolution(
                decision_at=normalized_decision_at,
                status="insufficient",
                resolver_version=self.resolver_version,
                resolver_hash=self._resolver_hash(()),
            )
        selected = available[0]
        return CanonicalResolution(
            security_id=selected.security_id,
            indicator_id=selected.indicator_id,
            decision_at=normalized_decision_at,
            status="resolved",
            selected=selected,
            candidates=available,
            confidence=selected.quality_score,
            resolver_version=self.resolver_version,
            resolver_hash=self._resolver_hash(available),
        )

    def _candidate_key(
        self,
        fact: StandardizedIndicatorFact,
    ) -> tuple[float, Decimal, int, float, str]:
        """candidate key."""
        priority = (
            self.provider_priority.index(fact.provider_code)
            if fact.provider_code in self.provider_priority
            else len(self.provider_priority)
        )
        return (
            -fact.event_at.timestamp(),
            -fact.quality_score,
            priority,
            -fact.fetched_at.timestamp(),
            fact.fact_id,
        )

    def _resolver_hash(self, candidates: tuple[StandardizedIndicatorFact, ...]) -> str:
        """resolver hash."""
        payload = "|".join(
            [
                self.resolver_version,
                ",".join(fact.fact_id for fact in candidates),
                ",".join(fact.provider_code for fact in candidates),
            ]
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
