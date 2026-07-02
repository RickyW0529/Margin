"""Quant-driven data requirement catalog tests."""

from __future__ import annotations

from margin.data.requirements import QuantDataRequirementCatalog


def test_catalog_contains_only_quant_consumed_tushare_endpoints() -> None:
    """The catalog must not backfill unrelated datasets merely because Pro exposes them."""
    catalog = QuantDataRequirementCatalog.default()

    enabled = {endpoint.api_name for endpoint in catalog.enabled_endpoints("tushare")}

    assert {
        "stock_basic",
        "namechange",
        "trade_cal",
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
        "index_classify",
        "index_member",
        "pledge_stat",
        "index_daily",
        "index_weight",
    } <= enabled
    assert {
        "top_list",
        "top_inst",
        "block_trade",
        "margin",
        "pledge_detail",
        "stk_holdernumber",
        "concept",
    }.isdisjoint(enabled)


def test_every_enabled_endpoint_has_an_active_quant_consumer() -> None:
    """No endpoint may be enabled without a traceable quant requirement."""
    catalog = QuantDataRequirementCatalog.default()

    for endpoint in catalog.enabled_endpoints("tushare"):
        requirements = catalog.requirements_for_endpoint(
            provider="tushare",
            api_name=endpoint.api_name,
        )
        assert requirements
        assert all(requirement.active for requirement in requirements)
        assert all(requirement.consumer for requirement in requirements)


def test_out_of_scope_endpoint_is_cataloged_without_sync_admission() -> None:
    """Known but unrelated endpoints remain auditable and cannot create partitions."""
    catalog = QuantDataRequirementCatalog.default()

    endpoint = catalog.endpoint("tushare", "top_list")

    assert endpoint.admission == "out_of_scope"
    assert endpoint.quant_requirement_codes == ()


def test_fina_indicator_natural_key_matches_real_response_fields() -> None:
    """The financial-indicator API does not return report_type."""
    endpoint = QuantDataRequirementCatalog.default().endpoint(
        "tushare",
        "fina_indicator",
    )

    assert endpoint.natural_key_fields == ("ts_code", "end_date", "ann_date")


def test_income_requirement_uses_raw_parent_profit_not_provider_ttm() -> None:
    """Income sync admits raw profit; y1/y2 are derived later by Feature Mart ETL."""
    catalog = QuantDataRequirementCatalog.default()
    requirement = next(
        item
        for item in catalog.requirements()
        if item.code == "income_fundamentals"
    )

    assert "n_income_attr_p" in requirement.warehouse_fields
    assert "net_profit_ttm" not in requirement.warehouse_fields
