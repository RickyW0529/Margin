"""Tests for ``AKShareProvider`` and ``TushareProvider``.

Acceptance: 0102.

Testing strategy: mock external SDK calls, verify field mapping, protocol integration,
point-in-time fields, and rate limiting. No real akshare/tushare APIs are invoked.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from margin.core.provider import MarketDataProvider
from margin.data.providers import AKShareProvider, TushareProvider


class TestAKShareProvider:
    """Unit tests for ``AKShareProvider`` covering descriptors, mapping, and health checks."""

    def test_descriptor(self):
        """The provider descriptor exposes the expected name, type and capabilities."""
        p = AKShareProvider()
        assert p.descriptor.name == "akshare"
        assert p.descriptor.provider_type.value == "market_data"
        assert "get_bars" in p.descriptor.capabilities
        assert p.descriptor.secret_refs == []

    def test_implements_market_data_protocol(self):
        """The provider implements the ``MarketDataProvider`` protocol."""
        p = AKShareProvider()
        assert isinstance(p, MarketDataProvider)

    def test_get_bars_field_mapping(self):
        """``get_bars`` maps Chinese column names to canonical fields and PIT timestamps."""
        p = AKShareProvider()

        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "日期": "2026-06-17",
                    "开盘": 10.5,
                    "收盘": 11.0,
                    "最高": 11.2,
                    "最低": 10.3,
                    "成交量": 1000000.0,
                    "成交额": 11000000.0,
                },
            ),
        ]

        with patch("akshare.stock_zh_a_hist", return_value=mock_df):
            bars = p.get_bars(
                ["000001.SZ"],
                datetime(2026, 6, 1),
                datetime(2026, 6, 18),
            )

        assert len(bars) == 1
        bar = bars[0]
        assert bar["symbol"] == "000001.SZ"
        assert bar["open"] == 10.5
        assert bar["close"] == 11.0
        assert bar["volume"] == 1000000.0
        assert bar["frequency"] == "1d"
        assert bar["source"] == "akshare"
        assert "fetched_at" in bar
        assert "available_at" in bar
        assert bar["available_at"] == datetime(2026, 6, 17, 15, 0)

    def test_get_bars_accepts_date_objects_from_current_akshare(self):
        """Current AKShare date objects map to a market-close availability time."""
        p = AKShareProvider()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "日期": date(2026, 6, 17),
                    "开盘": 10.5,
                    "收盘": 11.0,
                    "最高": 11.2,
                    "最低": 10.3,
                    "成交量": 1000000.0,
                    "成交额": 11000000.0,
                },
            ),
        ]

        with patch("akshare.stock_zh_a_hist", return_value=mock_df):
            bars = p.get_bars(
                ["000001.SZ"],
                datetime(2026, 6, 1),
                datetime(2026, 6, 18),
            )

        assert bars[0]["available_at"] == datetime(2026, 6, 17, 15, 0)

    def test_get_securities_field_mapping(self):
        """``get_securities`` maps raw security rows to canonical symbols and names."""
        p = AKShareProvider()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (0, {"代码": "000001", "名称": "平安银行", "最新价": 12.5}),
            (1, {"代码": "600000", "名称": "浦发银行", "最新价": 8.3}),
        ]

        with patch("akshare.stock_zh_a_spot_em", return_value=mock_df):
            securities = p.get_securities(datetime(2026, 6, 18))

        assert len(securities) == 2
        assert securities[0]["symbol"] == "000001.SZ"
        assert securities[1]["symbol"] == "600000.SH"
        assert securities[0]["name"] == "平安银行"
        assert securities[0]["source"] == "akshare"

    def test_get_index_members(self):
        """``get_index_members`` maps raw constituent rows to canonical symbols."""
        p = AKShareProvider()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (0, {"成份券代码": "000001", "成份券名称": "平安银行"}),
        ]

        with patch("akshare.index_stock_cons_csindex", return_value=mock_df):
            members = p.get_index_members("000300", datetime(2026, 6, 18))

        assert len(members) == 1
        assert members[0]["symbol"] == "000001.SZ"
        assert members[0]["index_code"] == "000300"
        assert members[0]["source"] == "akshare"

    def test_get_valuations(self):
        """``get_valuations`` maps Legulegu valuation history to canonical fields."""
        p = AKShareProvider()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "数据日期": "2026-06-17",
                    "PE(TTM)": 8.5,
                    "市净率": 0.9,
                    "市销率": 1.2,
                    "股息率": 3.1,
                    "总市值": 120_000_000_000,
                },
            )
        ]
        with patch("akshare.stock_value_em", return_value=mock_df):
            values = p.get_valuations(
                ["000001.SZ"],
                datetime(2026, 6, 1),
                datetime(2026, 6, 18),
            )

        assert values[0]["pe_ttm"] == 8.5
        assert values[0]["dividend_yield"] == 3.1
        assert values[0]["source"] == "akshare"

    def test_healthcheck_healthy(self):
        """A successful SDK call returns a healthy status."""
        p = AKShareProvider()
        with patch("akshare.stock_zh_a_spot_em", return_value=MagicMock()):
            result = p.healthcheck()
        assert result.status.value == "healthy"
        assert result.provider_name == "akshare"

    def test_healthcheck_unhealthy(self):
        """An SDK exception returns an unhealthy status containing the error."""
        p = AKShareProvider()
        with patch("akshare.stock_zh_a_spot_em", side_effect=Exception("network error")):
            result = p.healthcheck()
        assert result.status.value == "unhealthy"
        assert "network error" in result.message


class TestTushareProvider:
    """Unit tests for ``TushareProvider`` covering token handling, mapping, and health checks."""

    def test_descriptor(self):
        """The provider descriptor exposes the expected name, type and token secret ref."""
        p = TushareProvider(token="fake")
        assert p.descriptor.name == "tushare"
        assert p.descriptor.provider_type.value == "market_data"
        assert "tushare_token" in p.descriptor.secret_refs

    def test_implements_market_data_protocol(self):
        """The provider implements the ``MarketDataProvider`` protocol."""
        p = TushareProvider(token="fake")
        assert isinstance(p, MarketDataProvider)

    def test_set_token_resets_pro(self):
        """Setting a new token clears the cached ``pro`` client."""
        p = TushareProvider(token="old")
        p._pro = MagicMock()
        p.set_token("new")
        assert p._token == "new"
        assert p._pro is None

    def test_custom_http_url_is_applied_to_pro_client(self):
        """A custom Tushare-compatible endpoint is applied to the SDK client."""
        p = TushareProvider(token="fake", http_url="https://example.test/api")
        mock_pro = MagicMock()

        with patch("tushare.pro_api", return_value=mock_pro):
            assert p._ensure_pro() is mock_pro

        assert mock_pro._DataApi__http_url == "https://example.test/api"

    def test_get_bars_field_mapping(self):
        """``get_bars`` maps tushare daily fields to canonical fields and PIT timestamps."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "trade_date": "20260617",
                    "open": 10.5,
                    "close": 11.0,
                    "high": 11.2,
                    "low": 10.3,
                    "vol": 1000000.0,
                    "amount": 11000000.0,
                },
            ),
        ]
        mock_pro.daily.return_value = mock_df
        p._pro = mock_pro

        bars = p.get_bars(
            ["000001.SZ"],
            datetime(2026, 6, 1),
            datetime(2026, 6, 18),
        )

        assert len(bars) == 1
        bar = bars[0]
        assert bar["symbol"] == "000001.SZ"
        assert bar["open"] == 10.5
        assert bar["close"] == 11.0
        assert bar["volume"] == 100000000.0
        assert bar["amount"] == 11000000000.0
        assert bar["source"] == "tushare"
        assert bar["available_at"] == datetime(2026, 6, 17, 15, 0)
        mock_pro.daily.assert_called_once_with(
            ts_code="000001.SZ",
            start_date="20260601",
            end_date="20260618",
        )

    def test_get_securities_field_mapping(self):
        """``get_securities`` maps stock_basic rows to canonical security metadata."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "industry": "银行",
                    "market": "主板",
                    "list_date": "19910403",
                },
            ),
        ]
        mock_pro.stock_basic.return_value = mock_df
        p._pro = mock_pro

        securities = p.get_securities(datetime(2026, 6, 18))
        assert len(securities) == 1
        assert securities[0]["symbol"] == "000001.SZ"
        assert securities[0]["name"] == "平安银行"
        assert securities[0]["industry"] == "银行"
        assert securities[0]["source"] == "tushare"

    def test_get_adjustment_factors(self):
        """``get_adjustment_factors`` returns mapped adjustment factor records."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (0, {"trade_date": "20260617", "adj_factor": 1.5}),
        ]
        mock_pro.adj_factor.return_value = mock_df
        p._pro = mock_pro

        factors = p.get_adjustment_factors(
            ["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)
        )
        assert len(factors) == 1
        assert factors[0]["adj_factor"] == 1.5
        assert factors[0]["source"] == "tushare"

    def test_large_universe_bars_use_trade_date_cross_sections(self):
        """Full-A sync scales by trading date instead of one request per symbol."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_pro.daily.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260617",
                    "open": 10.0,
                    "close": 11.0,
                    "high": 11.2,
                    "low": 9.9,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        )
        p._pro = mock_pro

        bars = p.get_bars(
            [f"{index:06d}.SZ" for index in range(60)],
            datetime(2026, 6, 17),
            datetime(2026, 6, 17),
        )

        mock_pro.daily.assert_called_once_with(trade_date="20260617")
        assert bars[0]["symbol"] == "000001.SZ"

    def test_large_universe_adjustments_use_trade_date_cross_sections(self):
        """Full-A adjustment sync scales by trading date."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_pro.adj_factor.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260617",
                    "adj_factor": 1.5,
                }
            ]
        )
        p._pro = mock_pro

        factors = p.get_adjustment_factors(
            [f"{index:06d}.SZ" for index in range(60)],
            datetime(2026, 6, 17),
            datetime(2026, 6, 17),
        )

        mock_pro.adj_factor.assert_called_once_with(trade_date="20260617")
        assert factors[0]["symbol"] == "000001.SZ"

    def test_get_financials(self):
        """``get_financials`` maps fina_indicator rows to canonical financial fields."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (0, {"ann_date": "20260430", "roe": 0.12, "eps": 1.5, "gross_profit_margin": 0.3}),
        ]
        mock_pro.fina_indicator.return_value = mock_df
        p._pro = mock_pro

        financials = p.get_financials(
            ["000001.SZ"], datetime(2026, 1, 1), datetime(2026, 6, 18)
        )
        assert len(financials) == 1
        assert financials[0]["roe"] == 0.12
        assert financials[0]["source"] == "tushare"
        assert financials[0]["roe_ttm"] == 0.12

    def test_get_financials_derives_ttm_profit_from_pit_income_rows(self):
        """TTM profit uses latest annual plus current minus prior-year period."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_pro.fina_indicator.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20260430",
                    "end_date": "20260331",
                    "roe": 12.0,
                }
            ]
        )
        mock_pro.income.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20250331",
                    "end_date": "20241231",
                    "n_income_attr_p": 80.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20250430",
                    "end_date": "20250331",
                    "n_income_attr_p": 20.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20260331",
                    "end_date": "20251231",
                    "n_income_attr_p": 100.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20260430",
                    "end_date": "20260331",
                    "n_income_attr_p": 30.0,
                },
            ]
        )
        p._pro = mock_pro

        financials = p.get_financials(
            ["000001.SZ"],
            datetime(2025, 1, 1),
            datetime(2026, 6, 18),
        )

        assert financials[0]["net_profit_ttm"] == 110.0
        assert financials[0]["net_profit_y1"] == 100.0
        assert financials[0]["net_profit_y2"] == 80.0

    def test_large_universe_financials_use_paginated_cross_section(self):
        """Financial sync uses paginated market-wide calls for a large universe."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_pro.fina_indicator.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20260430",
                    "end_date": "20251231",
                    "roe": 12.0,
                    "grossprofit_margin": 35.0,
                    "netprofit_margin": 10.0,
                    "debt_to_assets": 45.0,
                    "tr_yoy": 8.0,
                    "netprofit_yoy": 9.0,
                }
            ]
        )
        mock_pro.income.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20260331",
                    "end_date": "20251231",
                    "n_income_attr_p": 100.0,
                }
            ]
        )
        p._pro = mock_pro

        financials = p.get_financials(
            [f"{index:06d}.SZ" for index in range(60)],
            datetime(2026, 1, 1),
            datetime(2026, 6, 18),
        )

        assert mock_pro.fina_indicator.call_count == 1
        assert "ts_code" not in mock_pro.fina_indicator.call_args.kwargs
        assert mock_pro.income.call_count == 1
        assert "ts_code" not in mock_pro.income.call_args.kwargs
        assert financials[0]["roe_ttm"] == 0.12
        assert financials[0]["liability_ratio"] == 0.45
        assert financials[0]["net_profit_ttm"] == 100.0

    def test_get_valuations(self):
        """``get_valuations`` maps daily_basic rows to canonical valuation fields."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "trade_date": "20260617",
                    "pe_ttm": 8.5,
                    "pb": 0.9,
                    "ps_ttm": 1.2,
                    "dv_ttm": 3.1,
                    "turnover_rate": 1.4,
                    "total_mv": 120_000,
                },
            )
        ]
        mock_pro.daily_basic.return_value = mock_df
        p._pro = mock_pro

        values = p.get_valuations(
            ["000001.SZ"],
            datetime(2026, 6, 1),
            datetime(2026, 6, 18),
        )

        assert values[0]["pe_ttm"] == 8.5
        assert values[0]["market_cap"] == 120_000_000
        assert values[0]["source"] == "tushare"

    def test_large_universe_valuations_use_trade_date_cross_sections(self):
        """Full-A valuation sync scales by trading date."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        mock_pro.daily_basic.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260617",
                    "pe_ttm": 8.5,
                    "pb": 0.9,
                    "ps_ttm": 1.2,
                    "dv_ttm": 3.1,
                    "turnover_rate": 1.4,
                    "total_mv": 120_000,
                }
            ]
        )
        p._pro = mock_pro

        values = p.get_valuations(
            [f"{index:06d}.SZ" for index in range(60)],
            datetime(2026, 6, 17),
            datetime(2026, 6, 17),
        )

        mock_pro.daily_basic.assert_called_once()
        assert "ts_code" not in mock_pro.daily_basic.call_args.kwargs
        assert values[0]["symbol"] == "000001.SZ"

    def test_healthcheck_healthy(self):
        """A configured pro client returns a healthy status."""
        p = TushareProvider(token="fake")
        mock_pro = MagicMock()
        p._pro = mock_pro
        result = p.healthcheck()
        assert result.status.value == "healthy"
        mock_pro.stock_basic.assert_called_once()

    def test_healthcheck_unhealthy(self):
        """An invalid token yields an unhealthy status."""
        p = TushareProvider(token="bad")
        with patch("tushare.pro_api", side_effect=Exception("invalid token")):
            result = p.healthcheck()
        assert result.status.value == "unhealthy"


class TestProviderRegistryIntegration:
    """Integration tests for provider registration and invocation via ``ProviderRegistry``."""

    def test_register_and_call_akshare(self, tmp_path, monkeypatch):
        """Registers ``AKShareProvider`` and calls ``get_bars`` through the registry.

        Verifies success tracking, response hashing, and audit logging.
        """
        from margin.core.audit import AuditLogger
        from margin.core.registry import ProviderRegistry
        from margin.core.secret import SecretManager

        monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "test")
        registry = ProviderRegistry(
            secret_manager=SecretManager(secrets_dir=tmp_path / "secrets"),
            audit_logger=AuditLogger(log_path=tmp_path / "audit.jsonl"),
        )

        provider = AKShareProvider()
        registry.register(provider)

        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (
                0,
                {
                    "日期": "2026-06-17",
                    "开盘": 10.0,
                    "收盘": 11.0,
                    "最高": 11.0,
                    "最低": 10.0,
                    "成交量": 100.0,
                    "成交额": 1000.0,
                },
            ),
        ]

        with patch("akshare.stock_zh_a_hist", return_value=mock_df):
            data, result = registry.call(
                "akshare", "get_bars",
                args=(["000001.SZ"], datetime(2026, 6, 1), datetime(2026, 6, 18)),
            )

        assert result.success is True
        assert result.provider_name == "akshare"
        assert result.response_hash.startswith("sha256:")
        assert len(data) == 1

        records = registry._audit_logger.read_all()
        assert len(records) == 1
        assert records[0].provider_name == "akshare"
