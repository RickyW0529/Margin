"""test_v1_migration_contract module."""

from __future__ import annotations

from pathlib import Path

VERSIONS_DIR = Path("alembic/versions")

V1_WAREHOUSE_COMPLETION_TABLES = (
    "hub_provider_endpoint",
    "hub_statement",
    "hub_trading_calendar",
    "hub_industry",
    "hub_backfill_campaign",
    "link_security_identifier",
    "link_security_industry",
    "link_security_daily_quote",
    "link_security_financial_statement",
    "link_security_corporate_action",
    "link_stock_pool_membership",
    "link_source_snapshot",
    "sat_security_name_history",
    "sat_identifier",
    "sat_industry_membership",
    "sat_listing_status",
    "sat_adjustment_factor",
    "sat_daily_basic",
    "sat_moneyflow",
    "sat_margin_detail",
    "sat_limit_status",
    "sat_suspend_status",
    "sat_financial_statement_income",
    "sat_financial_statement_balance",
    "sat_financial_statement_cashflow",
    "sat_forecast",
    "sat_express",
    "sat_dividend",
    "sat_corporate_action",
    "sat_document_metadata",
    "sat_document_text",
    "sat_news_article",
    "sat_document_embedding_metadata",
    "dim_date",
    "dim_company",
    "dim_industry",
    "dim_source",
    "dim_provider_endpoint",
    "dim_document",
    "dim_factor",
    "dim_run",
    "dim_strategy",
    "dim_backfill_campaign",
    "adjusted_price_fact",
    "daily_basic_fact",
    "moneyflow_fact",
    "margin_detail_fact",
    "financial_statement_fact",
    "financial_indicator_fact",
    "valuation_fact",
    "corporate_action_fact",
    "limit_suspend_fact",
    "stock_pool_membership_fact",
    "document_coverage_fact",
    "news_sentiment_fact",
    "data_quality_fact",
    "company_profile_page_v1",
    "data_freshness_panel_v1",
    "backfill_status_panel_v1",
    "research_run_trace_v1",
)


def _read(name: str) -> str:
    """Execute _read logic.

    Args:
        name: str: .

    Returns:
        str: .
    """
    return VERSIONS_DIR.joinpath(name).read_text(encoding="utf-8")


def test_v1_warehouse_migration_files_are_chained() -> None:
    """test_v1_warehouse_migration_files_are_chained implementation.

    Returns:
        None: .
    """
    assert 'down_revision = "20260708_0052_runtime_config"' in _read(
        "20260708_0053_v1_warehouse_schemas.py"
    )
    assert 'revision = "20260708_0053_v1_schemas"' in _read("20260708_0053_v1_warehouse_schemas.py")
    assert 'down_revision = "20260708_0053_v1_schemas"' in _read("20260708_0054_raw_ods_landing.py")
    assert 'down_revision = "20260708_0054_raw_ods"' in _read("20260708_0055_vault_pit_tables.py")
    assert 'down_revision = "20260708_0055_vault_pit"' in _read(
        "20260708_0056_kimball_mart_app_tables.py"
    )
    assert 'down_revision = "20260709_0058_runtime_cleanup"' in _read(
        "20260709_0059_complete_v1_warehouse_layers.py"
    )


def test_v1_warehouse_schemas_are_declared() -> None:
    """test_v1_warehouse_schemas_are_declared implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0053_v1_warehouse_schemas.py")

    for schema in (
        "raw_meta",
        "source_akshare",
        "source_filing",
        "source_news",
        "source_web",
        "source_doc",
        "ods",
        "vault",
        "mart_dw",
        "mart",
        "app",
        "agent",
        "tool",
        "prompt",
        "ops",
        "platform",
    ):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in migration


def test_raw_ods_tables_have_snapshot_lineage_and_available_at() -> None:
    """test_raw_ods_tables_have_snapshot_lineage_and_available_at implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0054_raw_ods_landing.py")

    for required in (
        "raw_data_snapshots",
        "raw_document_snapshots",
        "ods_daily_quote_raw",
        "raw_snapshot_id",
        "fetched_at",
        "available_at",
        "natural_key_hash",
        "revision_hash",
    ):
        assert required in migration


def test_vault_pit_tables_force_available_at() -> None:
    """test_vault_pit_tables_force_available_at implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0055_vault_pit_tables.py")

    for required in (
        "hub_security",
        "hub_company",
        "sat_daily_quote",
        "sat_financial_indicator",
        "pit_security_day",
        "pit_financial_statement",
        "pit_stock_pool_snapshot",
        "available_at",
        "published_at",
        "raw_snapshot_id",
    ):
        assert required in migration


def test_kimball_mart_app_tables_include_pit_safe_facts() -> None:
    """test_kimball_mart_app_tables_include_pit_safe_facts implementation.

    Returns:
        None: .
    """
    migration = _read("20260708_0056_kimball_mart_app_tables.py")

    for required in (
        "dim_stock",
        "daily_market_fact",
        "factor_fact",
        "factor_panel",
        "quant_candidate_mart",
        "stock_analysis_mart",
        "backtest_panel",
        "available_at",
        "feature_snapshot_id",
        "universe_snapshot_id",
    ):
        assert required in migration


def test_app_serving_tables_remain_part_of_data_warehouse_layers() -> None:
    """Ensure app-layer serving tables are retained as documented outputs.

    Returns:
        None: .
    """
    migration = _read("20260709_0058_drop_unused_v1_runtime_tables.py")

    assert 'op.drop_table("agent_answer_context_v1", schema="app")' not in migration
    assert 'op.drop_table("dashboard_items_v2", schema="app")' not in migration


def test_v1_warehouse_completion_migration_adds_missing_layers_and_adapters() -> None:
    """Ensure the 0059 migration completes the documented warehouse layers.

    Returns:
        None: .
    """
    migration = _read("20260709_0059_complete_v1_warehouse_layers.py")

    assert 'revision = "20260709_0059_warehouse_layers"' in migration
    for table_name in V1_WAREHOUSE_COMPLETION_TABLES:
        assert table_name in migration
    for required_adapter in (
        "INSERT INTO raw_meta.raw_data_snapshots",
        "INSERT INTO vault.hub_security",
        "INSERT INTO vault.sat_security_profile",
        "INSERT INTO mart_dw.dim_stock",
        "INSERT INTO mart_dw.daily_market_fact",
        "INSERT INTO mart.factor_panel",
        "INSERT INTO mart.quant_candidate_mart",
        "INSERT INTO mart.stock_analysis_mart",
        "INSERT INTO app.company_profile_page_v1",
        "CREATE MATERIALIZED VIEW mart.company_profile_view",
    ):
        assert required_adapter in migration
