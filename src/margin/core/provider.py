"""Provider type definitions, descriptors, base class, and business protocols.

This module defines the contracts that every Provider must satisfy, including
metadata descriptors, health check results, call results, and typed protocols
for specific capability domains such as market data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    """Capability category of a Provider.."""

    MARKET_DATA = "market_data"
    WEB_SEARCH = "web_search"
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VECTOR_STORE = "vector_store"
    NOTIFICATION = "notification"


class ProviderStatus(StrEnum):
    """Health status returned by a Provider health check.."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckResult(BaseModel):
    """Result of a Provider health check.."""

    provider_name: str
    status: ProviderStatus
    checked_at: datetime
    latency_ms: float | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CallResult(BaseModel):
    """Result of a Provider method call, including audit and cost metadata.."""

    provider_name: str
    provider_version: str
    success: bool
    data: Any = None
    error: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now())
    available_at: datetime | None = None
    response_hash: str | None = None
    cost: float = 0.0
    latency_ms: float | None = None
    attempt_count: int = 1
    from_fallback: bool = False


class ProviderDescriptor(BaseModel):
    """Immutable metadata descriptor for a Provider.."""

    name: str
    version: str
    provider_type: ProviderType
    capabilities: list[str] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class BaseProvider(ABC):
    """Abstract base class for all Providers.."""

    @property
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        """Return the metadata descriptor for this Provider.

        Returns:
            ProviderDescriptor: .
        """

    @abstractmethod
    def healthcheck(self) -> HealthCheckResult:
        """Execute a health check and return the status.

        Returns:
            HealthCheckResult: .
        """


# ---------------------------------------------------------------------------
# Business protocols — structural subtyping for Provider capability domains.
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for A-share market data Providers.."""

    def get_securities(self, as_of: datetime) -> list[dict[str, Any]]:
        """Return the universe of available securities as of a given date.

        Args:
            as_of: datetime: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[dict[str, Any]]:
        """Return OHLCV bars for the requested symbols and date range.

        Args:
            symbols: list[str]: .
            start: datetime: .
            end: datetime: .
            frequency: str: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...

    def get_adjustment_factors(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return adjustment factors for the requested symbols and date range.

        Args:
            symbols: list[str]: .
            start: datetime: .
            end: datetime: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...

    def get_financials(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return financial statement indicators for the requested symbols.

        Args:
            symbols: list[str]: .
            start: datetime: .
            end: datetime: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...

    def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]:
        """Return the constituents of an index as of a given date.

        Args:
            index_code: str: .
            as_of: datetime: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...


@runtime_checkable
class WebSearchProvider(Protocol):
    """Protocol for web search Providers.."""

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Execute a web search.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            list[dict[str, Any]]: .
        """
        ...
