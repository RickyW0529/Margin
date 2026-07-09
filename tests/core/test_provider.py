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
    """A configurable stub provider implementing ``BaseProvider`` for protocol tests.."""

    def __init__(self, name: str = "fake", version: str = "1.0.0") -> None:
        """Initialize the stub with a market-data descriptor.

        Args:
            name: str: .
            version: str: .

        Returns:
            None: .
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
        """Return the configured provider descriptor.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        """Return a healthy status for this provider.

        Returns:
            HealthCheckResult: .
        """
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=datetime.now(),
        )

    def get_securities(self, as_of):
        """Return a stub list of securities for the given date.

        Args:
            as_of: Any: .

        Returns:
            Any: .
        """
        return [{"symbol": "000001.SZ"}]

    def get_bars(self, symbols, start, end, frequency="1d"):
        """Return stub bar data for the given symbols.

        Args:
            symbols: Any: .
            start: Any: .
            end: Any: .
            frequency: Any: .

        Returns:
            Any: .
        """
        return [{"symbol": s, "close": 100.0} for s in symbols]

    def get_adjustment_factors(self, symbols, start, end):
        """Return stub adjustment factors for the given symbols.

        Args:
            symbols: Any: .
            start: Any: .
            end: Any: .

        Returns:
            Any: .
        """
        return [{"symbol": s, "factor": 1.0} for s in symbols]

    def get_financials(self, symbols, start, end):
        """Return stub financial data for the given symbols.

        Args:
            symbols: Any: .
            start: Any: .
            end: Any: .

        Returns:
            Any: .
        """
        return [{"symbol": s, "revenue": 1e8} for s in symbols]

    def get_index_members(self, index_code, as_of):
        """Return stub index members for the given index code.

        Args:
            index_code: Any: .
            as_of: Any: .

        Returns:
            Any: .
        """
        return [{"symbol": "000001.SZ", "index": index_code}]


class TestProviderDescriptor:
    """Tests covering ``ProviderDescriptor`` immutability and default values.."""

    def test_descriptor_is_frozen(self):
        """Test that a ``ProviderDescriptor`` cannot be modified after creation.

        Returns:
            Any: .
        """
        desc = ProviderDescriptor(
            name="akshare",
            version="1.0.0",
            provider_type=ProviderType.MARKET_DATA,
        )
        with pytest.raises(Exception):
            desc.name = "changed"

    def test_descriptor_defaults(self):
        """Test that optional descriptor fields default to empty containers.

        Returns:
            Any: .
        """
        desc = ProviderDescriptor(name="x", version="1", provider_type=ProviderType.LLM)
        assert desc.capabilities == []
        assert desc.secret_refs == []
        assert desc.config == {}


class TestBaseProvider:
    """Tests covering protocol conformance of a concrete ``BaseProvider``.."""

    def test_fake_provider_descriptor(self):
        """Test that the stub provider exposes the expected name and type.

        Returns:
            Any: .
        """
        p = FakeProvider()
        assert p.descriptor.name == "fake"
        assert p.descriptor.provider_type == ProviderType.MARKET_DATA

    def test_fake_provider_healthcheck(self):
        """Test that the stub provider reports itself as healthy.

        Returns:
            Any: .
        """
        p = FakeProvider()
        result = p.healthcheck()
        assert result.status == ProviderStatus.HEALTHY
        assert result.provider_name == "fake"

    def test_market_data_provider_protocol(self):
        """Test that a complete market-data implementation satisfies the protocol.

        Returns:
            Any: .
        """
        p = FakeProvider()
        assert isinstance(p, MarketDataProvider)

    def test_non_market_data_provider_fails_protocol(self):
        """Test that an incomplete provider does not satisfy the protocol.

        Returns:
            Any: .
        """

        class NonMarketProvider(BaseProvider):
            """A provider that does not satisfy the MarketDataProvider protocol.."""

            @property
            def descriptor(self):
                """Return the provider descriptor.

                Returns:
                    Any: .
                """
                return ProviderDescriptor(name="x", version="1", provider_type=ProviderType.LLM)

            def healthcheck(self):
                """Return a health check result.

                Returns:
                    Any: .
                """
                pass

        p = NonMarketProvider()
        assert not isinstance(p, MarketDataProvider)
