"""Tests for production research-tool wiring."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.research.production_tools import build_production_tool_registry
from margin.settings import MarginSettings


class FakeMarketDataProvider:
    def get_bars(self, symbols, start, end, frequency="1d"):
        del start, frequency
        return [
            {
                "symbol": symbol,
                "date": end,
                "close": 10.0 + index,
                "available_at": end,
            }
            for index, symbol in enumerate(symbols)
        ]

    def get_financials(self, symbols, start, end):
        del start
        return [
            {
                "symbol": symbol,
                "report_date": end,
                "total_assets": 100.0,
            }
            for symbol in symbols
        ]


class FailingMarketDataProvider:
    def get_bars(self, symbols, start, end, frequency="1d"):
        del symbols, start, end, frequency
        raise RuntimeError("provider unavailable")

    def get_financials(self, symbols, start, end):
        del symbols, start, end
        return []


def test_production_registry_configures_required_rule_tools():
    registry = build_production_tool_registry(
        MarginSettings(_env_file=None),
        market_data_provider=FakeMarketDataProvider(),
    )

    market = registry.call("market_data", {"symbol": "000001.SZ"})
    factor = registry.call(
        "factor",
        {"symbols": ["000001.SZ", "600000.SH"]},
    )
    portfolio = registry.call(
        "portfolio",
        {
            "symbol": "000001.SZ",
            "current_weight": 0.2,
            "max_weight": 0.1,
        },
    )
    retrieval = registry.call(
        "retrieval",
        {
            "symbol": "000001.SZ",
            "query": "经营",
            "decision_at": datetime(2026, 6, 19, tzinfo=UTC),
        },
    )

    assert market.success is True
    assert factor.success is True
    assert set(factor.data) == {"000001.SZ", "600000.SH"}
    assert portfolio.data["violations"]
    assert retrieval.success is True
    assert retrieval.data == []


def test_production_registry_degrades_market_data_without_aborting_workflow():
    registry = build_production_tool_registry(
        MarginSettings(_env_file=None),
        market_data_provider=FailingMarketDataProvider(),
    )

    market = registry.call("market_data", {"symbol": "000001.SZ"})
    factor = registry.call("factor", {"symbols": ["000001.SZ"]})

    assert market.success is True
    assert market.data["degraded"] is True
    assert factor.success is True
    assert factor.data == {"000001.SZ": 0.0}
