"""Tushare quant endpoint query-plan tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.tushare_query import TushareQueryCatalog


def test_every_admitted_endpoint_has_a_bounded_query_plan() -> None:
    """No admitted API may fall back to an unbounded generic crawl."""
    requirements = QuantDataRequirementCatalog.default()
    queries = TushareQueryCatalog.default()

    admitted = {
        endpoint.api_name
        for endpoint in requirements.enabled_endpoints("tushare")
    }

    assert set(queries.api_names()) == admitted
    assert all(queries.get(api_name).fields for api_name in admitted)
    assert all(queries.get(api_name).query_mode for api_name in admitted)


def test_probe_parameters_are_small_and_secret_free() -> None:
    """Real-seat probes must be low-volume and never serialize credentials."""
    catalog = TushareQueryCatalog.default()
    as_of = datetime(2026, 6, 23, tzinfo=UTC)

    for api_name in catalog.api_names():
        params = catalog.probe_params(
            api_name,
            as_of=as_of,
            sample_symbol="000001.SZ",
        )
        serialized = repr(params).lower()
        assert "token" not in serialized
        assert "api_key" not in serialized
        assert params.get("limit", 1) <= 100


def test_financial_query_plans_use_symbol_batches_for_current_proxy() -> None:
    """All-A financial backfill uses verified multi-symbol proxy calls."""
    catalog = TushareQueryCatalog.default()

    for api_name in (
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
        "pledge_stat",
    ):
        assert catalog.get(api_name).query_mode == "symbol_batch"
