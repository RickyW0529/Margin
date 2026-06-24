"""Migration coverage for the v0.2 data warehouse schema."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from scripts.verify_migrations import verify_clean_database


def test_data_warehouse_tables_exist(database_url: str) -> None:
    """Alembic head includes the production warehouse tables required by v0.2."""
    url = make_url(database_url)
    result = verify_clean_database(
        database_url,
        database_name=f"{url.database}_warehouse_migration",
        drop_existing=True,
    )

    assert {
        "provider_endpoints",
        "data_sync_runs",
        "standardized_indicator_facts",
        "canonical_indicator_values",
        "security_industry_memberships",
        "corporate_actions",
        "data_acquisition_policy_versions",
        "quant_data_requirements",
        "provider_endpoint_requirements",
        "source_quality_decisions",
        "source_tushare.ts_daily",
        "source_tushare.ts_income",
        "source_tushare.ts_pledge_stat",
        "source_akshare.ak_stock_zh_a_spot_em",
        "source_akshare.ak_stock_zh_a_hist",
        "source_akshare.ak_stock_balance_sheet_by_report_em",
        "source_akshare.ak_stock_value_em",
        "source_akshare.ak_index_stock_cons_csindex",
        "company_pool_snapshots",
        "company_pool_members",
    } <= set(result.tables)
