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
    """Capability category of a Provider."""

    MARKET_DATA = "market_data"
    WEB_SEARCH = "web_search"
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VECTOR_STORE = "vector_store"
    NOTIFICATION = "notification"


class ProviderStatus(StrEnum):
    """Health status returned by a Provider health check."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckResult(BaseModel):
    """Result of a Provider health check.

    Attributes:
        provider_name: Name of the checked Provider.
        status: Health status enum value.
        checked_at: Timestamp of the check.
        latency_ms: Check latency in milliseconds, if measured.
        message: Human-readable status message.
        details: Additional structured details.
    """

    provider_name: str
    status: ProviderStatus
    checked_at: datetime
    latency_ms: float | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CallResult(BaseModel):
    """Result of a Provider method call, including audit and cost metadata.

    Attributes:
        provider_name: Name of the called Provider.
        provider_version: Version of the Provider.
        success: Whether the call succeeded.
        data: Payload returned by the Provider method.
        error: Error message when the call failed.
        fetched_at: Timestamp when the call was attempted.
        available_at: Timestamp when the data becomes available.
        response_hash: SHA-256 hash of the response payload.
        cost: Estimated cost of the call.
        latency_ms: Round-trip latency in milliseconds.
        attempt_count: Number of attempts made before the final result.
        from_fallback: Whether the result came from a fallback Provider.
    """

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
    """Immutable metadata descriptor for a Provider.

    Describes the Provider's identity, capabilities, Secret references, and
    configuration. Sensitive credentials are never stored here; only reference
    names are kept.

    Attributes:
        name: Unique Provider name.
        version: Provider version string.
        provider_type: Capability category.
        capabilities: List of supported method names.
        secret_refs: List of Secret reference names required by the Provider.
        config: Provider-specific configuration dictionary.
    """

    name: str
    version: str
    provider_type: ProviderType
    capabilities: list[str] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class BaseProvider(ABC):
    """Abstract base class for all Providers.

    Subclasses must implement ``descriptor`` and ``healthcheck``. Concrete
    business methods (for example ``get_bars``) are defined by the typed
    protocols below.
    """

    @property
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        """Return the metadata descriptor for this Provider.

        Returns:
            The Provider's immutable ``ProviderDescriptor``.
        """

    @abstractmethod
    def healthcheck(self) -> HealthCheckResult:
        """Execute a health check and return the status.

        Returns:
            A ``HealthCheckResult`` describing the Provider's health.
        """


# ---------------------------------------------------------------------------
# Business protocols — structural subtyping for Provider capability domains.
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for A-share market data Providers.

    Defines the structural contract for Providers that supply securities,
    OHLCV bars, adjustment factors, financials, and index membership.
    """

    def get_securities(self, as_of: datetime) -> list[dict[str, Any]]:
        """Return the universe of available securities as of a given date.

        Args:
            as_of: Date for which the security universe is requested.

        Returns:
            List of security metadata records.
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
            symbols: List of standardized symbols (e.g. ``000001.SZ``).
            start: Start of the requested range.
            end: End of the requested range.
            frequency: Bar frequency (e.g. ``1d``, ``1w``, ``1M``).

        Returns:
            List of bar records.
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
            symbols: List of standardized symbols.
            start: Start of the requested range.
            end: End of the requested range.

        Returns:
            List of adjustment factor records.
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
            symbols: List of standardized symbols.
            start: Start of the requested reporting range.
            end: End of the requested reporting range.

        Returns:
            List of financial indicator records.
        """
        ...

    def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]:
        """Return the constituents of an index as of a given date.

        Args:
            index_code: Standardized index code.
            as_of: Date for which index membership is requested.

        Returns:
            List of index constituent records.
        """
        ...


@runtime_checkable
class WebSearchProvider(Protocol):
    """Protocol for web search Providers.

    Defines the structural contract for Providers that execute web search
    queries and return ranked result records.
    """

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Execute a web search.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of search result records.
        """
        ...
