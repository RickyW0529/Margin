"""Versioned, atomic capacity and budget governance."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from margin.core.db_orchestration import (
    CapacityLimitVersionRow,
)
from margin.sql.core_queries import (
    active_capacity_limit,
    capacity_counter_for_update,
    deprecate_active_limits,
    insert_capacity_counter,
)


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class CapacityConfigurationError(RuntimeError):
    """Raised when a requested capacity limit is missing or invalid."""


class CapacityOutcome(StrEnum):
    """Typed result used by workers to select a waiting state."""

    ALLOWED = "allowed"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    WAITING_BUDGET = "waiting_budget"


class CapacityLimit(BaseModel):
    """One immutable version of a count, token, or cost limit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version_id: str | None = Field(default=None, max_length=64)
    limit_key: str = Field(min_length=1, max_length=128)
    window_seconds: int = Field(gt=0)
    max_count: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost: Decimal | None = Field(default=None, gt=0)
    version: str = Field(min_length=1, max_length=64)
    config: dict[str, object] = Field(default_factory=dict)
    lifecycle: str = "active"
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_limit(self) -> Self:
        """validate limit."""
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if (
            self.max_count is None
            and self.max_tokens is None
            and self.max_cost is None
        ):
            raise ValueError("capacity limit requires at least one maximum")
        if self.version_id is None:
            digest = hashlib.sha256(
                f"{self.limit_key}\0{self.version}".encode()
            ).hexdigest()[:32]
            object.__setattr__(self, "version_id", f"cap_{digest}")
        return self

    @property
    def limit_type(self) -> str:
        """limit type."""
        dimensions = sum(
            value is not None
            for value in (self.max_count, self.max_tokens, self.max_cost)
        )
        if dimensions > 1:
            return "composite"
        if self.max_cost is not None:
            return "budget"
        if self.max_tokens is not None:
            return "tokens"
        return "rate"


class CapacityDecision(BaseModel):
    """Sanitized decision returned to orchestration workers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_key: str
    limit_version: str
    outcome: CapacityOutcome
    retry_after_seconds: int = Field(ge=0)
    current_count: int = Field(ge=0)
    current_tokens: int = Field(ge=0)
    current_cost: Decimal = Field(ge=0)

    @property
    def allowed(self) -> bool:
        """allowed."""
        return self.outcome == CapacityOutcome.ALLOWED


class CapacityUsage(BaseModel):
    """Atomic repository result after checking or recording usage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    request_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    cost_amount: Decimal = Field(ge=0)


class CapacityRepository(Protocol):
    """Atomic persistence contract for active limits and window counters."""

    def save_limit(self, limit: CapacityLimit) -> None:
        """Persist a capacity limit."""
        ...

    def get_active_limit(self, limit_key: str) -> CapacityLimit | None:
        """Retrieve the active limit for a given key."""
        ...

    def consume(
        self,
        limit: CapacityLimit,
        *,
        window_started_at: datetime,
        window_ends_at: datetime,
        count: int,
        tokens: int,
        cost: Decimal,
        enforce: bool,
    ) -> CapacityUsage:
        """Check and optionally record capacity consumption."""
        ...


class _Counter(BaseModel):
    """Counter."""
    request_count: int = 0
    token_count: int = 0
    cost_amount: Decimal = Decimal("0")


class MemoryCapacityRepository:
    """Thread-safe in-memory repository with the production atomic contract."""

    def __init__(self) -> None:
        """init  ."""
        self._lock = RLock()
        self._limits: dict[str, CapacityLimit] = {}
        self._counters: dict[tuple[str, str, datetime], _Counter] = {}

    def save_limit(self, limit: CapacityLimit) -> None:
        """save limit."""
        with self._lock:
            self._limits[limit.limit_key] = limit

    def get_active_limit(self, limit_key: str) -> CapacityLimit | None:
        """get active limit."""
        with self._lock:
            return self._limits.get(limit_key)

    def consume(
        self,
        limit: CapacityLimit,
        *,
        window_started_at: datetime,
        window_ends_at: datetime,
        count: int,
        tokens: int,
        cost: Decimal,
        enforce: bool,
    ) -> CapacityUsage:
        """consume."""
        del window_ends_at
        assert limit.version_id is not None
        key = (limit.limit_key, limit.version_id, window_started_at)
        with self._lock:
            current = self._counters.get(key, _Counter())
            allowed = _within_limit(current, limit, count, tokens, cost)
            if allowed or not enforce:
                current = _Counter(
                    request_count=current.request_count + count,
                    token_count=current.token_count + tokens,
                    cost_amount=current.cost_amount + cost,
                )
                self._counters[key] = current
            return CapacityUsage(
                allowed=allowed,
                request_count=current.request_count,
                token_count=current.token_count,
                cost_amount=current.cost_amount,
            )


class SQLAlchemyCapacityRepository:
    """PostgreSQL capacity repository using row locks for atomic consumption."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """init  ."""
        self._session_factory = session_factory

    def save_limit(self, limit: CapacityLimit) -> None:
        """save limit."""
        assert limit.version_id is not None
        try:
            with self._session_factory.begin() as session:
                existing = session.get(CapacityLimitVersionRow, limit.version_id)
                if existing is not None:
                    persisted = _limit_from_row(existing)
                    if persisted != limit:
                        raise ValueError(
                            f"capacity version '{limit.version_id}' has conflicting data"
                        )
                    if existing.lifecycle != "active":
                        session.execute(
                            deprecate_active_limits(limit.limit_key)
                        )
                        existing.lifecycle = "active"
                    return
                session.execute(
                    deprecate_active_limits(limit.limit_key)
                )
                session.add(_limit_to_row(limit))
        except IntegrityError as exc:
            raise ValueError(
                f"capacity limit activation conflict for '{limit.limit_key}'"
            ) from exc

    def get_active_limit(self, limit_key: str) -> CapacityLimit | None:
        """get active limit."""
        with self._session_factory() as session:
            row = session.scalar(active_capacity_limit(limit_key))
            return _limit_from_row(row) if row is not None else None

    def consume(
        self,
        limit: CapacityLimit,
        *,
        window_started_at: datetime,
        window_ends_at: datetime,
        count: int,
        tokens: int,
        cost: Decimal,
        enforce: bool,
    ) -> CapacityUsage:
        """consume."""
        assert limit.version_id is not None
        counter_id = _counter_id(limit.limit_key, limit.version_id, window_started_at)
        with self._session_factory.begin() as session:
            session.execute(
                insert_capacity_counter(
                    counter_id=counter_id,
                    limit_key=limit.limit_key,
                    limit_version_id=limit.version_id,
                    window_started_at=window_started_at,
                    window_ends_at=window_ends_at,
                )
            )
            row = session.scalar(
                capacity_counter_for_update(
                    limit.limit_key,
                    limit.version_id,
                    window_started_at,
                )
            )
            if row is None:
                raise RuntimeError("capacity counter could not be created")
            current = _Counter(
                request_count=row.request_count,
                token_count=row.token_count,
                cost_amount=row.cost_amount,
            )
            allowed = _within_limit(current, limit, count, tokens, cost)
            if allowed or not enforce:
                row.request_count += count
                row.token_count += tokens
                row.cost_amount += cost
                row.updated_at = _utc_now()
            return CapacityUsage(
                allowed=allowed,
                request_count=row.request_count,
                token_count=row.token_count,
                cost_amount=row.cost_amount,
            )


class CapacityGovernor:
    """High-level API mapping capacity denials to orchestration wait states."""

    def __init__(
        self,
        repository: CapacityRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """init  ."""
        self._repository = repository
        self._clock = clock

    def set_limits(self, limit: CapacityLimit) -> None:
        """set limits."""
        self._repository.save_limit(limit)

    def set_daily_budget(
        self,
        *,
        limit_key: str,
        max_cost: Decimal,
        version: str,
    ) -> None:
        """set daily budget."""
        self.set_limits(
            CapacityLimit(
                limit_key=limit_key,
                window_seconds=86_400,
                max_cost=max_cost,
                version=version,
            )
        )

    def try_acquire(
        self,
        limit_key: str,
        *,
        count: int = 1,
        tokens: int = 0,
    ) -> CapacityDecision:
        """try acquire."""
        return self._decide(
            limit_key,
            count=count,
            tokens=tokens,
            cost=Decimal("0"),
            enforce=True,
        )

    def try_acquire_budget(
        self,
        limit_key: str,
        *,
        estimated_cost: Decimal,
    ) -> CapacityDecision:
        """try acquire budget."""
        return self._decide(
            limit_key,
            count=0,
            tokens=0,
            cost=estimated_cost,
            enforce=True,
        )

    def record_cost(self, limit_key: str, cost: Decimal) -> CapacityDecision:
        """record cost."""
        return self._decide(
            limit_key,
            count=0,
            tokens=0,
            cost=cost,
            enforce=False,
        )

    def _decide(
        self,
        limit_key: str,
        *,
        count: int,
        tokens: int,
        cost: Decimal,
        enforce: bool,
    ) -> CapacityDecision:
        """decide."""
        if count < 0 or tokens < 0 or cost < 0:
            raise ValueError("capacity consumption cannot be negative")
        limit = self._repository.get_active_limit(limit_key)
        if limit is None:
            raise CapacityConfigurationError(
                f"active capacity limit '{limit_key}' is not configured"
            )
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("capacity clock must return timezone-aware datetime")
        window_started_at = _window_start(now, limit.window_seconds)
        window_ends_at = window_started_at + timedelta(seconds=limit.window_seconds)
        usage = self._repository.consume(
            limit,
            window_started_at=window_started_at,
            window_ends_at=window_ends_at,
            count=count,
            tokens=tokens,
            cost=cost,
            enforce=enforce,
        )
        outcome = CapacityOutcome.ALLOWED
        if not usage.allowed:
            outcome = (
                CapacityOutcome.WAITING_BUDGET
                if limit.max_cost is not None
                and usage.cost_amount + cost > limit.max_cost
                else CapacityOutcome.WAITING_RATE_LIMIT
            )
        return CapacityDecision(
            limit_key=limit.limit_key,
            limit_version=limit.version,
            outcome=outcome,
            retry_after_seconds=max(
                0,
                math.ceil((window_ends_at - now).total_seconds()),
            ),
            current_count=usage.request_count,
            current_tokens=usage.token_count,
            current_cost=usage.cost_amount,
        )


def _within_limit(
    current: _Counter,
    limit: CapacityLimit,
    count: int,
    tokens: int,
    cost: Decimal,
) -> bool:
    """Check whether the current counter values stay within the limit.

    Args:
        current: Current counter values for the window.
        limit: The capacity limit to enforce against.
        count: Additional request count to add.
        tokens: Additional token count to add.
        cost: Additional cost to add.

    Returns:
        True if the combined usage stays within the limit, False otherwise.
    """
    if (
        limit.max_count is not None
        and current.request_count + count > limit.max_count
    ):
        return False
    if limit.max_tokens is not None and current.token_count + tokens > limit.max_tokens:
        return False
    return not (
        limit.max_cost is not None and current.cost_amount + cost > limit.max_cost
    )


def _window_start(now: datetime, window_seconds: int) -> datetime:
    """Compute the start of the window containing the given timestamp.

    Args:
        now: Current timestamp.
        window_seconds: Duration of the window in seconds.

    Returns:
        The datetime representing the start of the window.
    """
    timestamp = int(now.timestamp())
    floored = timestamp - (timestamp % window_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


def _counter_id(limit_key: str, version_id: str, window_started_at: datetime) -> str:
    """Generate a deterministic counter ID for a limit window.

    Args:
        limit_key: Key identifying the limit.
        version_id: Version identifier of the limit.
        window_started_at: Start time of the window.

    Returns:
        A hex digest prefixed with ``counter_``.
    """
    digest = hashlib.sha256(
        f"{limit_key}\0{version_id}\0{window_started_at.isoformat()}".encode()
    ).hexdigest()[:32]
    return f"counter_{digest}"


def _limit_to_row(limit: CapacityLimit) -> CapacityLimitVersionRow:
    """Map a domain capacity limit to its SQLAlchemy row representation.

    Args:
        limit: The capacity limit to convert.

    Returns:
        The corresponding ORM row.
    """
    assert limit.version_id is not None
    return CapacityLimitVersionRow(
        version_id=limit.version_id,
        limit_key=limit.limit_key,
        version=limit.version,
        limit_type=limit.limit_type,
        window_seconds=limit.window_seconds,
        max_count=limit.max_count,
        max_tokens=limit.max_tokens,
        max_cost=limit.max_cost,
        config=dict(limit.config),
        lifecycle=limit.lifecycle,
        created_at=limit.created_at,
    )


def _limit_from_row(row: CapacityLimitVersionRow) -> CapacityLimit:
    """Map a SQLAlchemy row back to a domain capacity limit.

    Args:
        row: The ORM row to convert.

    Returns:
        The corresponding domain model.
    """
    return CapacityLimit(
        version_id=row.version_id,
        limit_key=row.limit_key,
        version=row.version,
        window_seconds=row.window_seconds,
        max_count=row.max_count,
        max_tokens=row.max_tokens,
        max_cost=row.max_cost,
        config=dict(row.config),
        lifecycle=row.lifecycle,
        created_at=row.created_at,
    )
