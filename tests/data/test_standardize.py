"""字段标准化模块测试 — 0103 验收。"""

from __future__ import annotations

from datetime import datetime

import pytest

from margin.data.standardize import (
    DataDomain,
    StandardDataEvent,
    Standardizer,
    TimeStandardizer,
    UnitConverter,
    normalize_symbol,
    symbol_components,
)


class TestNormalizeSymbol:
    def test_pure_digit_sh(self):
        assert normalize_symbol("600000") == "600000.SH"

    def test_pure_digit_sz(self):
        assert normalize_symbol("000001") == "000001.SZ"

    def test_already_standard(self):
        assert normalize_symbol("000001.SZ") == "000001.SZ"

    def test_prefix_format(self):
        assert normalize_symbol("SZ000001") == "000001.SZ"
        assert normalize_symbol("SH600000") == "600000.SH"

    def test_lowercase(self):
        assert normalize_symbol("000001.sz") == "000001.SZ"

    def test_688_star(self):
        assert normalize_symbol("688981") == "688981.SH"

    def test_invalid_passthrough(self):
        assert normalize_symbol("FOO") == "FOO"


class TestSymbolComponents:
    def test_split(self):
        code, exchange = symbol_components("000001.SZ")
        assert code == "000001"
        assert exchange == "SZ"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            symbol_components("000001")


class TestUnitConverter:
    def test_yuan_passthrough(self):
        assert UnitConverter.convert_amount(100.0, "yuan") == 100.0

    def test_wan_yuan(self):
        assert UnitConverter.convert_amount(1.5, "wan_yuan") == 15000.0

    def test_yi_yuan(self):
        assert UnitConverter.convert_amount(2.0, "yi_yuan") == 200000000.0

    def test_qian_yuan(self):
        assert UnitConverter.convert_amount(2.0, "qian_yuan") == 2000.0

    def test_volume_gu(self):
        assert UnitConverter.convert_volume(100.0, "gu") == 100.0

    def test_volume_shou(self):
        assert UnitConverter.convert_volume(5.0, "shou") == 500.0


class TestTimeStandardizer:
    def test_parse_yyyymmdd(self):
        dt = TimeStandardizer.parse_date("20260617")
        assert dt == datetime(2026, 6, 17)

    def test_parse_iso(self):
        dt = TimeStandardizer.parse_date("2026-06-17")
        assert dt == datetime(2026, 6, 17)

    def test_parse_datetime_obj(self):
        original = datetime(2026, 6, 17, 15, 0, 0)
        assert TimeStandardizer.parse_date(original) is original

    def test_parse_none(self):
        assert TimeStandardizer.parse_date(None) is None

    def test_parse_empty(self):
        assert TimeStandardizer.parse_date("") is None

    def test_parse_invalid(self):
        assert TimeStandardizer.parse_date("not-a-date") is None

    def test_to_pit_fields_defaults(self):
        pit = TimeStandardizer.to_pit_fields()
        assert "event_at" in pit
        assert "published_at" in pit
        assert "available_at" in pit
        assert "fetched_at" in pit
        assert pit["revised_at"] is None

    def test_to_pit_fields_explicit(self):
        event = datetime(2026, 6, 17)
        published = datetime(2026, 6, 18)
        pit = TimeStandardizer.to_pit_fields(
            event_at=event, published_at=published
        )
        assert pit["event_at"] == event
        assert pit["published_at"] == published
        assert pit["available_at"] == published


class TestStandardDataEvent:
    def test_frozen(self):
        event = StandardDataEvent(
            domain=DataDomain.MARKET_BAR,
            symbol="000001.SZ",
            data={"close": 11.0},
            event_at=datetime(2026, 6, 17),
            published_at=datetime(2026, 6, 17),
            available_at=datetime(2026, 6, 17),
            fetched_at=datetime(2026, 6, 18),
            source="akshare",
        )
        with pytest.raises(Exception):
            event.symbol = "changed"


class TestStandardizer:
    def setup_method(self):
        self.std = Standardizer(mapping_version="v1")

    def test_standardize_bars(self):
        raw = [
            {
                "symbol": "000001",
                "date": datetime(2026, 6, 17),
                "open": 10.5,
                "close": 11.0,
                "high": 11.2,
                "low": 10.3,
                "volume": 1000000.0,
                "amount": 11000000.0,
                "frequency": "1d",
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = self.std.standardize_bars(raw, source="akshare")
        assert len(events) == 1
        event = events[0]
        assert event.domain == DataDomain.MARKET_BAR
        assert event.symbol == "000001.SZ"
        assert event.data["close"] == 11.0
        assert event.source == "akshare"
        assert event.mapping_version == "v1"
        assert event.event_at == datetime(2026, 6, 17)
        assert event.available_at == datetime(2026, 6, 17, 15, 0)

    def test_standardize_bars_applies_units(self):
        raw = [
            {
                "symbol": "000001",
                "date": datetime(2026, 6, 17),
                "open": 10.5,
                "close": 11.0,
                "high": 11.2,
                "low": 10.3,
                "volume": 5.0,
                "volume_unit": "shou",
                "amount": 2.0,
                "amount_unit": "qian_yuan",
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = self.std.standardize_bars(raw, source="tushare")
        assert events[0].data["volume"] == 500.0
        assert events[0].data["amount"] == 2000.0

    def test_standardize_financials_without_available_at_uses_fetched_at(self):
        fetched_at = datetime(2026, 6, 18, 20, 0)
        raw = [
            {
                "symbol": "000001.SZ",
                "report_date": datetime(2026, 3, 31),
                "roe": 0.12,
                "fetched_at": fetched_at,
            },
        ]
        events = self.std.standardize_financials(raw, source="akshare")
        assert events[0].available_at == fetched_at

    def test_standardize_securities(self):
        raw = [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "industry": "银行",
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = self.std.standardize_securities(raw, source="akshare")
        assert len(events) == 1
        assert events[0].domain == DataDomain.SECURITY_META
        assert events[0].symbol == "000001.SZ"
        assert events[0].data["name"] == "平安银行"

    def test_standardize_financials(self):
        raw = [
            {
                "symbol": "000001.SZ",
                "report_date": datetime(2026, 3, 31),
                "roe": 0.12,
                "eps": 1.5,
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = self.std.standardize_financials(raw, source="tushare")
        assert len(events) == 1
        assert events[0].domain == DataDomain.FINANCIAL
        assert events[0].data["roe"] == 0.12
        assert events[0].event_at == datetime(2026, 3, 31)

    def test_standardize_index_members(self):
        raw = [
            {
                "symbol": "000001",
                "index_code": "000300",
                "name": "平安银行",
                "weight": 0.5,
                "as_of": datetime(2026, 6, 18),
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = self.std.standardize_index_members(raw, source="akshare")
        assert len(events) == 1
        assert events[0].domain == DataDomain.INDEX_MEMBER
        assert events[0].symbol == "000001.SZ"
        assert events[0].data["index_code"] == "000300"
        assert events[0].data["weight"] == 0.5

    def test_standardize_bars_empty(self):
        events = self.std.standardize_bars([], source="akshare")
        assert events == []

    def test_cross_source_consistency(self):
        """同一股票在 akshare/tushare 两个源经标准化后 symbol 一致。"""
        akshare_raw = [
            {
                "symbol": "000001",
                "date": datetime(2026, 6, 17),
                "close": 11.0,
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        tushare_raw = [
            {
                "symbol": "000001.SZ",
                "date": datetime(2026, 6, 17),
                "close": 11.0,
                "fetched_at": datetime(2026, 6, 18),
            },
        ]

        ak_events = self.std.standardize_bars(akshare_raw, source="akshare")
        ts_events = self.std.standardize_bars(tushare_raw, source="tushare")

        assert ak_events[0].symbol == ts_events[0].symbol == "000001.SZ"
        assert ak_events[0].data["close"] == ts_events[0].data["close"]
