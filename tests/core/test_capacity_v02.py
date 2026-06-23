"""Capacity and budget governance contracts for v0.2 workers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete

from margin.core.capacity import (
    CapacityGovernor,
    CapacityLimit,
    CapacityOutcome,
    MemoryCapacityRepository,
    SQLAlchemyCapacityRepository,
)
from margin.core.db_orchestration import (
    CapacityLimitVersionRow,
    ProviderCapacityCounterRow,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


class MutableClock:
    """MutableClock."""
    def __init__(self, now: datetime) -> None:
        """Initialize the instance."""
        self.now = now

    def __call__(self) -> datetime:
        """call  ."""
        return self.now


def _clock() -> MutableClock:
    """clock."""
    return MutableClock(datetime(2026, 6, 22, 12, 0, tzinfo=UTC))


def test_provider_rpm_limit_returns_waiting_rate_limit() -> None:
    """provider rpm limit returns waiting rate limit."""
    clock = _clock()
    governor = CapacityGovernor(MemoryCapacityRepository(), clock=clock)
    governor.set_limits(
        CapacityLimit(
            limit_key="provider:tavily:rpm",
            window_seconds=60,
            max_count=1,
            version="limits-v0.2.0",
        )
    )

    assert governor.try_acquire("provider:tavily:rpm").outcome == CapacityOutcome.ALLOWED

    denied = governor.try_acquire("provider:tavily:rpm")

    assert denied.outcome == CapacityOutcome.WAITING_RATE_LIMIT
    assert denied.retry_after_seconds == 60


def test_llm_daily_cost_limit_returns_waiting_budget() -> None:
    """llm daily cost limit returns waiting budget."""
    clock = _clock()
    governor = CapacityGovernor(MemoryCapacityRepository(), clock=clock)
    governor.set_daily_budget(
        limit_key="llm:cost",
        max_cost=Decimal("1.00"),
        version="limits-v0.2.0",
    )
    governor.record_cost("llm:cost", Decimal("0.95"))

    denied = governor.try_acquire_budget(
        "llm:cost",
        estimated_cost=Decimal("0.10"),
    )

    assert denied.outcome == CapacityOutcome.WAITING_BUDGET
    assert denied.current_cost == Decimal("0.95")


def test_rate_window_rollover_allows_new_request() -> None:
    """rate window rollover allows new request."""
    clock = _clock()
    governor = CapacityGovernor(MemoryCapacityRepository(), clock=clock)
    governor.set_limits(
        CapacityLimit(
            limit_key="provider:tushare:rpm",
            window_seconds=60,
            max_count=1,
            version="limits-v0.2.0",
        )
    )
    assert governor.try_acquire("provider:tushare:rpm").allowed is True
    assert governor.try_acquire("provider:tushare:rpm").allowed is False

    clock.now += timedelta(seconds=60)

    assert governor.try_acquire("provider:tushare:rpm").allowed is True


def test_capacity_version_switch_does_not_reuse_prior_counter() -> None:
    """capacity version switch does not reuse prior counter."""
    clock = _clock()
    governor = CapacityGovernor(MemoryCapacityRepository(), clock=clock)
    governor.set_limits(
        CapacityLimit(
            limit_key="provider:tavily:rpm",
            window_seconds=60,
            max_count=1,
            version="limits-v0.2.0",
        )
    )
    assert governor.try_acquire("provider:tavily:rpm").allowed is True
    assert governor.try_acquire("provider:tavily:rpm").allowed is False

    governor.set_limits(
        CapacityLimit(
            limit_key="provider:tavily:rpm",
            window_seconds=60,
            max_count=2,
            version="limits-v0.2.1",
        )
    )

    decision = governor.try_acquire("provider:tavily:rpm")
    assert decision.allowed is True
    assert decision.limit_version == "limits-v0.2.1"


def test_memory_capacity_acquire_is_atomic_under_concurrency() -> None:
    """memory capacity acquire is atomic under concurrency."""
    clock = _clock()
    governor = CapacityGovernor(MemoryCapacityRepository(), clock=clock)
    governor.set_limits(
        CapacityLimit(
            limit_key="worker:concurrency",
            window_seconds=60,
            max_count=5,
            version="limits-v0.2.0",
        )
    )

    with ThreadPoolExecutor(max_workers=20) as executor:
        decisions = list(
            executor.map(
                lambda _: governor.try_acquire("worker:concurrency"),
                range(20),
            )
        )

    assert sum(decision.allowed for decision in decisions) == 5
    assert sum(not decision.allowed for decision in decisions) == 15


def test_postgres_capacity_switches_version_within_same_window(
    database_url: str,
) -> None:
    """postgres capacity switches version within same window."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    limit_key = "provider:test-version-switch:rpm"
    with session_factory.begin() as session:
        session.execute(
            delete(ProviderCapacityCounterRow).where(
                ProviderCapacityCounterRow.limit_key == limit_key
            )
        )
        session.execute(
            delete(CapacityLimitVersionRow).where(
                CapacityLimitVersionRow.limit_key == limit_key
            )
        )

    governor = CapacityGovernor(
        SQLAlchemyCapacityRepository(session_factory),
        clock=_clock(),
    )

    try:
        governor.set_limits(
            CapacityLimit(
                limit_key=limit_key,
                window_seconds=60,
                max_count=1,
                version="limits-v0.2.0",
            )
        )
        assert governor.try_acquire(limit_key).allowed is True
        assert governor.try_acquire(limit_key).allowed is False

        governor.set_limits(
            CapacityLimit(
                limit_key=limit_key,
                window_seconds=60,
                max_count=2,
                version="limits-v0.2.1",
            )
        )

        assert governor.try_acquire(limit_key).allowed is True
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(ProviderCapacityCounterRow).where(
                    ProviderCapacityCounterRow.limit_key == limit_key
                )
            )
            session.execute(
                delete(CapacityLimitVersionRow).where(
                    CapacityLimitVersionRow.limit_key == limit_key
                )
            )
        engine.dispose()
