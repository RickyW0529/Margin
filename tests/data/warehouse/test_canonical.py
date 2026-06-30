"""Canonical indicator resolution tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from margin.data.canonical import CanonicalResolver
from margin.data.facts import StandardizedIndicatorFact

DECISION = datetime(2026, 6, 22, tzinfo=UTC)


def fact(
    *,
    provider_code: str = "akshare",
    quality_score: Decimal = Decimal("0.80"),
    available_at: datetime = DECISION,
    event_at: datetime = DECISION,
) -> StandardizedIndicatorFact:
    """Build a ``StandardizedIndicatorFact`` fixture with overridable attributes."""
    return StandardizedIndicatorFact(
        fact_id=f"fact-{provider_code}-{quality_score}",
        provider_code=provider_code,
        provider_fact_id=f"{provider_code}-raw-1",
        endpoint_code="daily_bar",
        security_id="000001.SZ",
        indicator_id="close",
        indicator_version="indicator-v0.2.0",
        event_at=event_at,
        available_at=available_at,
        fetched_at=DECISION,
        numeric_value=Decimal("12.34"),
        unit="CNY",
        quality_score=quality_score,
        mapping_version="mapping-v0.2.0",
        raw_snapshot_id="raw-1",
    )


def test_canonical_keeps_all_provider_candidates() -> None:
    """Test that the canonical resolver retains all provider candidates and selects the best."""
    resolver = CanonicalResolver()

    result = resolver.resolve(
        [
            fact(provider_code="akshare", quality_score=Decimal("0.80")),
            fact(provider_code="tushare", quality_score=Decimal("0.90")),
        ],
        decision_at=DECISION,
    )

    assert result.status == "resolved"
    assert result.selected is not None
    assert result.selected.provider_code == "tushare"
    assert {candidate.provider_code for candidate in result.candidates} == {
        "akshare",
        "tushare",
    }


def test_future_fact_is_not_candidate() -> None:
    """Test that a fact available after the decision time is excluded from candidates."""
    resolver = CanonicalResolver()

    result = resolver.resolve(
        [fact(available_at=DECISION + timedelta(seconds=1))],
        decision_at=DECISION,
    )

    assert result.status == "insufficient"
    assert result.selected is None
    assert result.candidates == ()


def test_canonical_prefers_latest_business_event_before_provider_quality() -> None:
    """The current canonical value must represent the latest available period."""
    resolver = CanonicalResolver()

    result = resolver.resolve(
        [
            fact(
                provider_code="tushare",
                quality_score=Decimal("0.99"),
                event_at=DECISION - timedelta(days=1),
            ),
            fact(
                provider_code="akshare",
                quality_score=Decimal("0.80"),
                event_at=DECISION,
            ),
        ],
        decision_at=DECISION,
    )

    assert result.selected is not None
    assert result.selected.event_at == DECISION
