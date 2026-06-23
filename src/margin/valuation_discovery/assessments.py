"""Effective assessment pointer service."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from margin.valuation_discovery.models import EffectiveAssessmentPointer


class EffectiveAssessmentService:
    """Build effective assessment pointer events from terminal review outcomes."""

    _KEEP_PREVIOUS_STALE = {"abstain", "review_deferred"}
    _KEEP_PREVIOUS_VERIFIED = {"carry_forward_verified"}
    _USE_NEW = {"update_assessment", "downgrade_confidence", "invalidate"}

    def apply_review_result(
        self,
        *,
        security_id: str,
        scope_version_id: str,
        previous_effective_assessment_id: str | None,
        current_review_outcome: str,
        new_assessment_id: str | None,
        stale_reason: str | None,
        last_successful_data_check_at: datetime | None = None,
        last_successful_news_check_at: datetime | None = None,
        effective_from: datetime | None = None,
    ) -> EffectiveAssessmentPointer:
        """Create and persist the next effective assessment pointer."""
        outcome = current_review_outcome.strip().lower()
        if outcome in self._KEEP_PREVIOUS_STALE:
            if previous_effective_assessment_id is None:
                raise ValueError(
                    f"cannot {outcome} without a previous assessment"
                )
            effective_assessment_id = previous_effective_assessment_id
            freshness = "stale"
            final_stale_reason = stale_reason or outcome
        elif outcome in self._KEEP_PREVIOUS_VERIFIED:
            if previous_effective_assessment_id is None:
                raise ValueError("cannot carry forward without a previous assessment")
            effective_assessment_id = previous_effective_assessment_id
            freshness = "verified"
            final_stale_reason = None
        elif outcome in self._USE_NEW:
            if new_assessment_id is None:
                raise ValueError("new_assessment_id is required")
            effective_assessment_id = new_assessment_id
            freshness = "current"
            final_stale_reason = None
        else:
            raise ValueError(f"unsupported review outcome: {current_review_outcome}")

        pointer_effective_from = effective_from or datetime.now(UTC)
        pointer = EffectiveAssessmentPointer(
            pointer_id=_pointer_id(
                security_id=security_id,
                scope_version_id=scope_version_id,
                effective_assessment_id=effective_assessment_id,
                effective_from=pointer_effective_from,
            ),
            security_id=security_id,
            scope_version_id=scope_version_id,
            effective_assessment_id=effective_assessment_id,
            effective_from=pointer_effective_from,
            previous_assessment_id=(
                previous_effective_assessment_id
                if effective_assessment_id != previous_effective_assessment_id
                else None
            ),
            assessment_freshness=allocation_freshness(freshness),
            stale_reason=final_stale_reason,
            last_successful_data_check_at=last_successful_data_check_at,
            last_successful_news_check_at=last_successful_news_check_at,
            created_at=pointer_effective_from,
        )
        return pointer


def allocation_freshness(value: str) -> str:
    """Return a validated assessment freshness value."""
    if value not in {"current", "stale", "verified"}:
        raise ValueError(f"unsupported assessment freshness: {value}")
    return value


def _pointer_id(
    *,
    security_id: str,
    scope_version_id: str,
    effective_assessment_id: str,
    effective_from: datetime,
) -> str:
    """Build an idempotent pointer event ID."""
    material = "|".join(
        (
            security_id,
            scope_version_id,
            effective_assessment_id,
            effective_from.isoformat(),
        )
    )
    return "eap_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
