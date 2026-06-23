"""Provider endpoint descriptors and registry for data warehouse sync."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DuplicateEndpointError(ValueError):
    """Raised when a provider/code endpoint is registered more than once."""


class UnknownEndpointError(KeyError):
    """Raised when a provider/code endpoint lookup misses."""


class BackfillPolicy(BaseModel):
    """Backfill settings for an endpoint."""

    mode: str = "incremental"
    default_lookback_days: int = Field(default=365, ge=0)
    max_lookback_days: int | None = Field(default=None, ge=0)
    supports_full_refresh: bool = True

    model_config = {"frozen": True}


class RateLimitPolicy(BaseModel):
    """Endpoint rate-limit settings used by sync workers."""

    requests_per_minute: int = Field(default=60, ge=1)
    burst: int = Field(default=1, ge=1)
    retry_after_seconds: int = Field(default=60, ge=1)

    model_config = {"frozen": True}


class ProviderEndpoint(BaseModel):
    """Versioned provider endpoint descriptor.

    Endpoint definitions are global data-source contracts. They are not scoped to
    user research scopes; downstream scope filtering happens after warehouse sync.
    """

    provider: str
    code: str
    domain: str
    enabled: bool = True
    backfill: BackfillPolicy = Field(default_factory=BackfillPolicy)
    revision_lookback_days: int = Field(default=7, ge=0)
    rate_limit: RateLimitPolicy = Field(default_factory=RateLimitPolicy)
    schema_version: str = "endpoint-v0.2.0"
    description: str = ""
    params_schema: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("provider", "code", "domain")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        """Normalize endpoint identity fields."""
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("endpoint identity fields must be non-empty")
        return normalized

    @property
    def endpoint_id(self) -> str:
        """Return stable provider/code identity."""
        return f"{self.provider}:{self.code}"


class ProviderEndpointRegistry:
    """In-memory endpoint registry used by sync planning."""

    def __init__(self, endpoints: Iterable[ProviderEndpoint] | None = None) -> None:
        """Initialize the instance."""
        self._endpoints: dict[tuple[str, str], ProviderEndpoint] = {}
        for endpoint in endpoints or ():
            self.register(endpoint)

    def register(self, endpoint: ProviderEndpoint) -> None:
        """Register an endpoint, rejecting duplicate provider/code pairs."""
        key = (endpoint.provider, endpoint.code)
        if key in self._endpoints:
            raise DuplicateEndpointError(
                f"provider endpoint already registered: {endpoint.provider}/{endpoint.code}"
            )
        self._endpoints[key] = endpoint

    def get(self, provider: str, code: str) -> ProviderEndpoint:
        """Return an endpoint descriptor by provider/code."""
        key = (provider.strip().lower(), code.strip().lower())
        try:
            return self._endpoints[key]
        except KeyError as exc:
            raise UnknownEndpointError(f"unknown provider endpoint: {provider}/{code}") from exc

    def list(
        self,
        *,
        provider: str | None = None,
        domain: str | None = None,
    ) -> tuple[ProviderEndpoint, ...]:
        """List endpoint descriptors, optionally filtered by provider and domain."""
        normalized_provider = provider.strip().lower() if provider else None
        normalized_domain = domain.strip().lower() if domain else None
        return tuple(
            endpoint
            for endpoint in sorted(self._endpoints.values(), key=lambda item: item.endpoint_id)
            if (normalized_provider is None or endpoint.provider == normalized_provider)
            and (normalized_domain is None or endpoint.domain == normalized_domain)
        )

    @classmethod
    def default(cls) -> ProviderEndpointRegistry:
        """Build the default AKShare/Tushare endpoint registry."""
        endpoints: list[ProviderEndpoint] = []
        for provider in ("akshare", "tushare"):
            endpoints.extend(
                [
                    ProviderEndpoint(
                        provider=provider,
                        code="security_master",
                        domain="security",
                        backfill=BackfillPolicy(default_lookback_days=0),
                        description="A-share security master and provider identifiers",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="daily_bar",
                        domain="market",
                        backfill=BackfillPolicy(default_lookback_days=10),
                        description="A-share daily market bars",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="adjustment_factor",
                        domain="corporate_action",
                        backfill=BackfillPolicy(default_lookback_days=30),
                        description="Daily adjustment factors",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="financial_statement",
                        domain="financial",
                        backfill=BackfillPolicy(default_lookback_days=540),
                        revision_lookback_days=540,
                        description="Financial statements and derived indicators",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="valuation",
                        domain="valuation",
                        backfill=BackfillPolicy(default_lookback_days=10),
                        description="Daily valuation metrics",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="index_member_csi300",
                        domain="universe",
                        backfill=BackfillPolicy(default_lookback_days=30),
                        description="CSI 300 constituent membership",
                    ),
                    ProviderEndpoint(
                        provider=provider,
                        code="index_member_csi500",
                        domain="universe",
                        backfill=BackfillPolicy(default_lookback_days=30),
                        description="CSI 500 constituent membership",
                    ),
                ]
            )
        return cls(endpoints)
