"""Domain-aware freshness expectation and status calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class DataDomain(StrEnum):
    """Warehouse data domains with different freshness semantics."""

    MARKET = "market"
    VALUATION = "valuation"
    FINANCIAL = "financial"
    FILING = "filing"
    NEWS = "news"


class FreshnessStatus(StrEnum):
    """Current freshness status for an endpoint/domain."""

    FRESH = "fresh"
    STALE = "stale"
    SYNCING = "syncing"
    FAILED = "failed"
    NEVER_SYNCED = "never_synced"


@dataclass(frozen=True)
class FreshnessExpectation:
    """Expected data availability for a domain at a decision time."""

    domain: DataDomain
    as_of_date: date
    expected_at: datetime


@dataclass(frozen=True)
class FreshnessState:
    """Calculated freshness status from expected and observed availability."""

    domain: DataDomain
    as_of_date: date
    expected_at: datetime
    observed_at: datetime | None
    status: FreshnessStatus
    lag_seconds: int | None


class FreshnessCalculator:
    """Calculate expected-as-of dates and freshness states.

    Market and valuation data follow the trading calendar and provider
    availability time. Filing/news use natural-day freshness. Fundamentals are
    expected after a configurable disclosure lag because disclosure availability
    is event-driven rather than guaranteed every trading day.
    """

    def __init__(
        self,
        *,
        trading_days: set[date],
        timezone: str = "Asia/Shanghai",
        market_available_time: time = time(18, 0),
        natural_day_available_time: time = time(23, 59),
        financial_disclosure_lag_days: int = 1,
    ) -> None:
        """Initialize the instance."""
        if not trading_days:
            raise ValueError("trading_days must not be empty")
        self._trading_days = frozenset(trading_days)
        self._timezone = ZoneInfo(timezone)
        self._market_available_time = market_available_time
        self._natural_day_available_time = natural_day_available_time
        self._financial_disclosure_lag_days = financial_disclosure_lag_days

    def expected_as_of(self, domain: DataDomain | str, *, now: datetime) -> FreshnessExpectation:
        """Return the expected data cut-off for a domain at ``now``."""
        normalized_domain = DataDomain(domain)
        local_now = _as_timezone(now, self._timezone)
        if normalized_domain in {DataDomain.MARKET, DataDomain.VALUATION}:
            as_of_date = self._expected_market_date(local_now)
            expected_at = datetime.combine(
                as_of_date,
                self._market_available_time,
                tzinfo=self._timezone,
            )
            return FreshnessExpectation(
                domain=normalized_domain,
                as_of_date=as_of_date,
                expected_at=expected_at,
            )
        if normalized_domain is DataDomain.FINANCIAL:
            as_of_date = local_now.date() - timedelta(days=self._financial_disclosure_lag_days)
            expected_at = datetime.combine(
                as_of_date,
                self._natural_day_available_time,
                tzinfo=self._timezone,
            )
            return FreshnessExpectation(
                domain=normalized_domain,
                as_of_date=as_of_date,
                expected_at=expected_at,
            )
        as_of_date = local_now.date()
        expected_at = datetime.combine(
            as_of_date,
            self._natural_day_available_time,
            tzinfo=self._timezone,
        )
        return FreshnessExpectation(
            domain=normalized_domain,
            as_of_date=as_of_date,
            expected_at=expected_at,
        )

    def evaluate(
        self,
        domain: DataDomain | str,
        *,
        now: datetime,
        latest_observed_at: datetime | None,
        syncing: bool = False,
        failed: bool = False,
    ) -> FreshnessState:
        """Evaluate freshness from an expected cut-off and latest observation."""
        expectation = self.expected_as_of(domain, now=now)
        if failed:
            return _state(expectation, latest_observed_at, FreshnessStatus.FAILED)
        if syncing:
            return _state(expectation, latest_observed_at, FreshnessStatus.SYNCING)
        if latest_observed_at is None:
            return _state(expectation, None, FreshnessStatus.NEVER_SYNCED)
        observed_at = _as_timezone(latest_observed_at, self._timezone)
        if observed_at >= expectation.expected_at:
            return _state(expectation, observed_at, FreshnessStatus.FRESH, lag_seconds=0)
        lag_seconds = int((expectation.expected_at - observed_at).total_seconds())
        return _state(
            expectation,
            observed_at,
            FreshnessStatus.STALE,
            lag_seconds=lag_seconds,
        )

    def _expected_market_date(self, local_now: datetime) -> date:
        """expected market date."""
        candidate = local_now.date()
        if (
            candidate in self._trading_days
            and local_now.timetz().replace(tzinfo=None) >= self._market_available_time
        ):
            return candidate
        return self._previous_trading_day(candidate)

    def _previous_trading_day(self, before_or_on: date) -> date:
        """previous trading day."""
        previous = [trading_day for trading_day in self._trading_days if trading_day < before_or_on]
        if previous:
            return max(previous)
        return min(self._trading_days)


def _state(
    expectation: FreshnessExpectation,
    observed_at: datetime | None,
    status: FreshnessStatus,
    *,
    lag_seconds: int | None = None,
) -> FreshnessState:
    """state."""
    return FreshnessState(
        domain=expectation.domain,
        as_of_date=expectation.as_of_date,
        expected_at=expectation.expected_at,
        observed_at=observed_at,
        status=status,
        lag_seconds=lag_seconds,
    )


def _as_timezone(value: datetime, timezone: ZoneInfo) -> datetime:
    """as timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)
