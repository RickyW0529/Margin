"""ProviderDescriptor 与 Provider 基类协议测试。"""

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
    def __init__(self, name: str = "fake", version: str = "1.0.0") -> None:
        self._descriptor = ProviderDescriptor(
            name=name,
            version=version,
            provider_type=ProviderType.MARKET_DATA,
            capabilities=["get_bars", "get_financials"],
            secret_refs=["fake_token"],
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=datetime.now(),
        )

    def get_securities(self, as_of):
        return [{"symbol": "000001.SZ"}]

    def get_bars(self, symbols, start, end, frequency="1d"):
        return [{"symbol": s, "close": 100.0} for s in symbols]

    def get_adjustment_factors(self, symbols, start, end):
        return [{"symbol": s, "factor": 1.0} for s in symbols]

    def get_financials(self, symbols, start, end):
        return [{"symbol": s, "revenue": 1e8} for s in symbols]

    def get_index_members(self, index_code, as_of):
        return [{"symbol": "000001.SZ", "index": index_code}]


class TestProviderDescriptor:
    def test_descriptor_is_frozen(self):
        desc = ProviderDescriptor(
            name="akshare",
            version="1.0.0",
            provider_type=ProviderType.MARKET_DATA,
        )
        with pytest.raises(Exception):
            desc.name = "changed"

    def test_descriptor_defaults(self):
        desc = ProviderDescriptor(
            name="x", version="1", provider_type=ProviderType.LLM
        )
        assert desc.capabilities == []
        assert desc.secret_refs == []
        assert desc.config == {}


class TestBaseProvider:
    def test_fake_provider_descriptor(self):
        p = FakeProvider()
        assert p.descriptor.name == "fake"
        assert p.descriptor.provider_type == ProviderType.MARKET_DATA

    def test_fake_provider_healthcheck(self):
        p = FakeProvider()
        result = p.healthcheck()
        assert result.status == ProviderStatus.HEALTHY
        assert result.provider_name == "fake"

    def test_market_data_provider_protocol(self):
        p = FakeProvider()
        assert isinstance(p, MarketDataProvider)

    def test_non_market_data_provider_fails_protocol(self):
        class NonMarketProvider(BaseProvider):
            @property
            def descriptor(self):
                return ProviderDescriptor(
                    name="x", version="1", provider_type=ProviderType.LLM
                )

            def healthcheck(self):
                pass

        p = NonMarketProvider()
        assert not isinstance(p, MarketDataProvider)
