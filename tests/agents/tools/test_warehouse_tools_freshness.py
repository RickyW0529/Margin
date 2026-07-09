"""Tests for warehouse data-freshness tool wiring."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from margin.agents.tools.warehouse_tools import WarehouseReadTools
from margin.data.freshness import FreshnessStatus


class _FakeWarehouse:
    def freshness(self, domains=None):
        assert domains is None or "market" in domains
        return [
            SimpleNamespace(
                provider="tushare",
                endpoint_code="daily",
                as_of_date=date(2026, 7, 8),
                expected_at=datetime(2026, 7, 8, 10, tzinfo=UTC),
                observed_at=datetime(2026, 7, 8, 11, tzinfo=UTC),
                status=FreshnessStatus.FRESH,
                lag_seconds=0,
            ),
            SimpleNamespace(
                provider="tushare",
                endpoint_code="fina_indicator",
                as_of_date=date(2026, 7, 1),
                expected_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
                observed_at=None,
                status=FreshnessStatus.STALE,
                lag_seconds=86_400,
            ),
        ]


def test_query_data_freshness_returns_aggregate_and_records() -> None:
    tools = WarehouseReadTools(_FakeWarehouse())
    result = tools.query_data_freshness(domains=("market",))
    assert result.tool_name == "warehouse.query_data_freshness"
    assert result.output["status"] == "stale"
    assert result.output["record_count"] == 2
    assert result.output["records"][0]["status"] == "fresh"


def test_query_data_freshness_filters_by_dataset() -> None:
    tools = WarehouseReadTools(_FakeWarehouse())
    result = tools.query_data_freshness(dataset="daily")
    assert result.output["record_count"] == 1
    assert result.output["records"][0]["endpoint_code"] == "daily"
    assert result.output["status"] == "fresh"


def test_default_catalog_registers_freshness_tool() -> None:
    from margin.agents.tools.catalog import default_tool_catalog

    catalog = default_tool_catalog(warehouse_repository=_FakeWarehouse())
    assert catalog.has("warehouse.query_data_freshness", "v1")
