"""Quant-driven data requirement catalog tests."""

from __future__ import annotations

from margin.data.requirements import QuantDataRequirementCatalog


def test_catalog_contains_only_quant_consumed_tushare_endpoints() -> None:
    """The catalog must not backfill unrelated datasets merely because Pro exposes them.

    Returns:
        None: .
    """
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
        "moneyflow",
        "margin_detail",
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
        "forecast",
        "express",
        "index_classify",
        "index_member",
        "pledge_stat",
        "index_daily",
        "index_weight",
        "limit_list_d",
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
    """No endpoint may be enabled without a traceable quant requirement.

    Returns:
        None: .
    """
    catalog = QuantDataRequirementCatalog.default()

    for endpoint in catalog.enabled_endpoints("tushare"):
        requirements = catalog.requirements_for_endpoint(
            provider="tushare",
            api_name=endpoint.api_name,
        )
        assert requirements
        assert all(requirement.active for requirement in requirements)
        assert all(requirement.consumer for requirement in requirements)


def test_ml_lifecycle_baseline_requirements_are_traceable_to_endpoints() -> None:
    """ML lifecycle serving features must be visible in the data admission catalog.

    Returns:
        None: .
    """
    catalog = QuantDataRequirementCatalog.default()
    ml_requirements = {
        item.code: item
        for item in catalog.requirements()
        if item.consumer.startswith("MLLifecycleQuantStrategy")
    }

    assert set(ml_requirements) == {
        "ml_lifecycle_market_features",
        "ml_lifecycle_fundamental_features",
        "ml_lifecycle_industry_stage",
        "ml_lifecycle_flow_features",
        "ml_lifecycle_execution_risk",
    }
    assert "return_6m_ex_1m" in ml_requirements["ml_lifecycle_market_features"].warehouse_fields
    assert "revenue_yoy" in ml_requirements["ml_lifecycle_fundamental_features"].warehouse_fields
    assert (
        "industry_lifecycle_score"
        in ml_requirements["ml_lifecycle_industry_stage"].warehouse_fields
    )
    assert "mf_lg_net_amount" in ml_requirements["ml_lifecycle_flow_features"].warehouse_fields
    assert "limit_trade_blocked" in ml_requirements["ml_lifecycle_execution_risk"].warehouse_fields

    endpoint_links = {
        endpoint: {
            requirement.code
            for requirement in catalog.requirements_for_endpoint(
                provider="tushare",
                api_name=endpoint,
            )
        }
        for endpoint in (
            "daily",
            "adj_factor",
            "daily_basic",
            "fina_indicator",
            "income",
            "moneyflow",
            "margin_detail",
            "forecast",
            "express",
            "index_member",
            "suspend_d",
            "limit_list_d",
        )
    }
    assert "ml_lifecycle_market_features" in endpoint_links["daily"]
    assert "ml_lifecycle_market_features" in endpoint_links["daily_basic"]
    assert "ml_lifecycle_fundamental_features" in endpoint_links["fina_indicator"]
    assert "ml_lifecycle_fundamental_features" in endpoint_links["income"]
    assert "ml_lifecycle_industry_stage" in endpoint_links["index_member"]
    assert "ml_lifecycle_execution_risk" in endpoint_links["suspend_d"]
    assert "ml_lifecycle_flow_features" in endpoint_links["moneyflow"]
    assert "ml_lifecycle_flow_features" in endpoint_links["margin_detail"]
    assert "ml_lifecycle_flow_features" in endpoint_links["forecast"]
    assert "ml_lifecycle_flow_features" in endpoint_links["express"]
    assert "ml_lifecycle_execution_risk" in endpoint_links["limit_list_d"]


def test_out_of_scope_endpoint_is_cataloged_without_sync_admission() -> None:
    """Known but unrelated endpoints remain auditable and cannot create partitions.

    Returns:
        None: .
    """
    catalog = QuantDataRequirementCatalog.default()

    endpoint = catalog.endpoint("tushare", "top_list")

    assert endpoint.admission == "out_of_scope"
    assert endpoint.quant_requirement_codes == ()


def test_fina_indicator_natural_key_matches_real_response_fields() -> None:
    """The financial-indicator API does not return report_type.

    Returns:
        None: .
    """
    endpoint = QuantDataRequirementCatalog.default().endpoint(
        "tushare",
        "fina_indicator",
    )

    assert endpoint.natural_key_fields == ("ts_code", "end_date", "ann_date")


def test_income_requirement_uses_raw_parent_profit_not_provider_ttm() -> None:
    """Income sync admits raw profit; y1/y2 are derived later by Feature Mart ETL.

    Returns:
        None: .
    """
    catalog = QuantDataRequirementCatalog.default()
    requirement = next(
        item for item in catalog.requirements() if item.code == "income_fundamentals"
    )

    assert "n_income_attr_p" in requirement.warehouse_fields
    assert "net_profit_ttm" not in requirement.warehouse_fields
