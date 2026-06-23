"""Tests for ``ProviderDescriptor`` and ``BaseProvider`` protocol compliance."""

from datetime import datetime

import pytest

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    MarketDataProvider,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)


class FakeProvider(BaseProvider):
    """A configurable stub provider implementing ``BaseProvider`` for protocol tests.

    Attributes:
        _descriptor: The provider descriptor exposed via ``descriptor``.
    """

    def __init__(self, name: str = "fake", version: str = "1.0.0") -> None:
        """Initialize the stub with a market-data descriptor.

        Args:
            name: Provider name returned by the descriptor.
            version: Provider version returned by the descriptor.
        """
        self._descriptor = ProviderDescriptor(
            name=name,
            version=version,
            provider_type=ProviderType.MARKET_DATA,
            capabilities=["get_bars", "get_financials"],
            secret_refs=["fake_token"],
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Returns:
            The configured provider descriptor.
        """
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        """Returns:
            A healthy status for this provider.
        """
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=datetime.now(),
        )

    def get_securities(self, as_of):
        """get securities."""
        return [{"symbol": "000001.SZ"}]

    def get_bars(self, symbols, start, end, frequency="1d"):
        """get bars."""
        return [{"symbol": s, "close": 100.0} for s in symbols]

    def get_adjustment_factors(self, symbols, start, end):
        """get adjustment factors."""
        return [{"symbol": s, "factor": 1.0} for s in symbols]

    def get_financials(self, symbols, start, end):
        """get financials."""
        return [{"symbol": s, "revenue": 1e8} for s in symbols]

    def get_index_members(self, index_code, as_of):
        """get index members."""
        return [{"symbol": "000001.SZ", "index": index_code}]


class TestProviderDescriptor:
    """Tests covering ``ProviderDescriptor`` immutability and default values."""

    def test_descriptor_is_frozen(self):
        """A ``ProviderDescriptor`` cannot be modified after creation."""
        desc = ProviderDescriptor(
            name="akshare",
            version="1.0.0",
            provider_type=ProviderType.MARKET_DATA,
        )
        with pytest.raises(Exception):
            desc.name = "changed"

    def test_descriptor_defaults(self):
        """Optional descriptor fields default to empty containers when omitted."""
        desc = ProviderDescriptor(
            name="x", version="1", provider_type=ProviderType.LLM
        )
        assert desc.capabilities == []
        assert desc.secret_refs == []
        assert desc.config == {}


class TestBaseProvider:
    """Tests covering protocol conformance of a concrete ``BaseProvider``."""

    def test_fake_provider_descriptor(self):
        """The stub provider exposes the expected name and type."""
        p = FakeProvider()
        assert p.descriptor.name == "fake"
        assert p.descriptor.provider_type == ProviderType.MARKET_DATA

    def test_fake_provider_healthcheck(self):
        """The stub provider reports itself as healthy."""
        p = FakeProvider()
        result = p.healthcheck()
        assert result.status == ProviderStatus.HEALTHY
        assert result.provider_name == "fake"

    def test_market_data_provider_protocol(self):
        """A complete market-data implementation satisfies the ``MarketDataProvider`` protocol."""
        p = FakeProvider()
        assert isinstance(p, MarketDataProvider)

    def test_non_market_data_provider_fails_protocol(self):
        """An incomplete provider does not satisfy the ``MarketDataProvider`` protocol."""
        class NonMarketProvider(BaseProvider):
            """A provider that does not satisfy the MarketDataProvider protocol."""

            @property
            def descriptor(self):
                """Return the provider descriptor."""
                return ProviderDescriptor(
                    name="x", version="1", provider_type=ProviderType.LLM
                )

            def healthcheck(self):
                """Return a health check result."""
                pass

        p = NonMarketProvider()
        assert not isinstance(p, MarketDataProvider)
