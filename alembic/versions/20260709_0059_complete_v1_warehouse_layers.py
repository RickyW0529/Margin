"""Complete v1 PIT warehouse layers and legacy adapters.

Revision ID: 20260709_0059_warehouse_layers
Revises: 20260709_0058_runtime_cleanup
Create Date: 2026-07-09 12:30:00
"""

from __future__ import annotations

# ruff: noqa: E501
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260709_0059_warehouse_layers"
down_revision = "20260709_0058_runtime_cleanup"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return the PostgreSQL JSONB type used by warehouse payload columns."""
    return postgresql.JSONB(astext_type=sa.Text())


def _text_array() -> postgresql.ARRAY:
    """Return a PostgreSQL text array type."""
    return postgresql.ARRAY(sa.Text())


def _vault_tracking_columns() -> list[sa.Column]:
    """Return common Data Vault satellite tracking columns."""
    return [
        sa.Column("hashdiff", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("system_to", sa.DateTime(timezone=True)),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _create_security_satellite(table_name: str, *payload_columns: sa.Column) -> None:
    """Create a security-owned satellite with standard PIT lineage columns."""
    op.create_table(
        table_name,
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        *payload_columns,
        *_vault_tracking_columns(),
        schema="vault",
    )
    op.create_index(
        f"ix_{table_name}_pit",
        table_name,
        ["security_hk", "available_at"],
        schema="vault",
    )


def _create_stock_fact(table_name: str, *metric_columns: sa.Column) -> None:
    """Create a stock/date fact table with PIT-safe lineage columns."""
    op.create_table(
        table_name,
        sa.Column("fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("stock_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_stock.stock_key"), nullable=False),
        *metric_columns,
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_snapshot_id", sa.Text()),
        sa.Column("feature_snapshot_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="mart_dw",
    )
    op.create_index(
        f"ix_{table_name}_date_stock",
        table_name,
        ["date_key", "stock_key"],
        schema="mart_dw",
    )
    op.create_index(
        f"ix_{table_name}_available",
        table_name,
        ["available_at"],
        schema="mart_dw",
    )


def upgrade() -> None:
    """Complete the documented warehouse layers and seed adapter rows."""
    _add_missing_pit_columns()
    _create_missing_vault_hubs()
    _create_missing_vault_links()
    _create_missing_vault_satellites()
    _create_missing_kimball_dimensions()
    _create_missing_kimball_facts()
    _create_missing_app_serving_tables()
    _create_company_profile_materialized_view()
    _backfill_from_legacy_tables()


def _add_missing_pit_columns() -> None:
    """Add PIT references required by the v1 design document."""
    op.add_column("pit_security_day", sa.Column("moneyflow_sat_id", sa.BigInteger()), schema="vault")
    op.add_column("pit_security_day", sa.Column("margin_detail_sat_id", sa.BigInteger()), schema="vault")


def _create_missing_vault_hubs() -> None:
    """Create Data Vault hubs not introduced by the earlier representative migration."""
    op.create_table(
        "hub_provider_endpoint",
        sa.Column("provider_endpoint_hk", sa.Text(), primary_key=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.UniqueConstraint("provider_name", "endpoint_name", name="uq_hub_provider_endpoint_business_key"),
        schema="vault",
    )
    op.create_table(
        "hub_statement",
        sa.Column("statement_hk", sa.Text(), primary_key=True),
        sa.Column("statement_key", sa.Text(), nullable=False),
        sa.Column("statement_type", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.UniqueConstraint("statement_key", "statement_type", name="uq_hub_statement_business_key"),
        schema="vault",
    )
    op.create_table(
        "hub_trading_calendar",
        sa.Column("calendar_hk", sa.Text(), primary_key=True),
        sa.Column("exchange_code", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.UniqueConstraint("exchange_code", "trade_date", name="uq_hub_trading_calendar_business_key"),
        schema="vault",
    )
    op.create_table(
        "hub_industry",
        sa.Column("industry_hk", sa.Text(), primary_key=True),
        sa.Column("taxonomy", sa.Text(), nullable=False),
        sa.Column("industry_code", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.UniqueConstraint("taxonomy", "industry_code", name="uq_hub_industry_business_key"),
        schema="vault",
    )
    op.create_table(
        "hub_backfill_campaign",
        sa.Column("backfill_campaign_hk", sa.Text(), primary_key=True),
        sa.Column("campaign_id", sa.Text(), nullable=False, unique=True),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )


def _create_missing_vault_links() -> None:
    """Create named Data Vault links for entity relationships and source lineage."""
    op.create_table(
        "link_security_identifier",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("identifier_system", sa.Text(), nullable=False),
        sa.Column("identifier_value", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_industry",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("industry_hk", sa.Text(), sa.ForeignKey("vault.hub_industry.industry_hk"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_daily_quote",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("provider_endpoint_hk", sa.Text(), sa.ForeignKey("vault.hub_provider_endpoint.provider_endpoint_hk")),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_financial_statement",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("statement_hk", sa.Text(), sa.ForeignKey("vault.hub_statement.statement_hk"), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_corporate_action",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("corporate_action_key", sa.Text(), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_stock_pool_membership",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("pool_name", sa.Text(), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_source_snapshot",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("source_hk", sa.Text(), sa.ForeignKey("vault.hub_source.source_hk"), nullable=False),
        sa.Column("provider_endpoint_hk", sa.Text(), sa.ForeignKey("vault.hub_provider_endpoint.provider_endpoint_hk")),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )


def _create_missing_vault_satellites() -> None:
    """Create the remaining satellites required by the PIT warehouse contract."""
    _create_security_satellite("sat_security_name_history", sa.Column("name", sa.Text(), nullable=False))
    _create_security_satellite(
        "sat_identifier",
        sa.Column("identifier_system", sa.Text(), nullable=False),
        sa.Column("identifier_value", sa.Text(), nullable=False),
    )
    _create_security_satellite(
        "sat_industry_membership",
        sa.Column("industry_hk", sa.Text(), sa.ForeignKey("vault.hub_industry.industry_hk")),
        sa.Column("taxonomy", sa.Text()),
        sa.Column("industry_code", sa.Text()),
        sa.Column("industry_name", sa.Text()),
    )
    _create_security_satellite(
        "sat_listing_status",
        sa.Column("listing_status", sa.Text(), nullable=False),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
    )
    _create_security_satellite(
        "sat_adjustment_factor",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("adjustment_factor", sa.Numeric()),
    )
    _create_security_satellite(
        "sat_daily_basic",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("turnover_rate", sa.Numeric()),
        sa.Column("pe", sa.Numeric()),
        sa.Column("pb", sa.Numeric()),
        sa.Column("total_mv", sa.Numeric()),
        sa.Column("circ_mv", sa.Numeric()),
    )
    _create_security_satellite(
        "sat_moneyflow",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("buy_sm_amount", sa.Numeric()),
        sa.Column("sell_sm_amount", sa.Numeric()),
        sa.Column("net_mf_amount", sa.Numeric()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _create_security_satellite(
        "sat_margin_detail",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rzye", sa.Numeric()),
        sa.Column("rqye", sa.Numeric()),
        sa.Column("rzrqye", sa.Numeric()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _create_security_satellite(
        "sat_limit_status",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("limit_status", sa.Text()),
        sa.Column("up_limit", sa.Numeric()),
        sa.Column("down_limit", sa.Numeric()),
    )
    _create_security_satellite(
        "sat_suspend_status",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("suspend_status", sa.Text()),
        sa.Column("suspend_reason", sa.Text()),
    )
    for table_name, statement_type in (
        ("sat_financial_statement_income", "income"),
        ("sat_financial_statement_balance", "balance"),
        ("sat_financial_statement_cashflow", "cashflow"),
    ):
        _create_security_satellite(
            table_name,
            sa.Column("report_period", sa.Date(), nullable=False),
            sa.Column("statement_type", sa.Text(), nullable=False, server_default=statement_type),
            sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        )
    _create_security_satellite(
        "sat_forecast",
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("forecast_type", sa.Text()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _create_security_satellite(
        "sat_express",
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _create_security_satellite(
        "sat_dividend",
        sa.Column("announcement_date", sa.Date()),
        sa.Column("ex_date", sa.Date()),
        sa.Column("cash_amount", sa.Numeric()),
        sa.Column("share_ratio", sa.Numeric()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _create_security_satellite(
        "sat_corporate_action",
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_table(
        "sat_document_metadata",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_hk", sa.Text(), sa.ForeignKey("vault.hub_document.document_hk"), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("source_url", sa.Text()),
        *_vault_tracking_columns(),
        schema="vault",
    )
    op.create_table(
        "sat_document_text",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_hk", sa.Text(), sa.ForeignKey("vault.hub_document.document_hk"), nullable=False),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_hash", sa.Text()),
        *_vault_tracking_columns(),
        schema="vault",
    )
    op.create_table(
        "sat_news_article",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_hk", sa.Text(), sa.ForeignKey("vault.hub_document.document_hk"), nullable=False),
        sa.Column("source_name", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("sentiment_label", sa.Text()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_vault_tracking_columns(),
        schema="vault",
    )
    op.create_table(
        "sat_document_embedding_metadata",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_hk", sa.Text(), sa.ForeignKey("vault.hub_document.document_hk"), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        *_vault_tracking_columns(),
        schema="vault",
    )


def _create_missing_kimball_dimensions() -> None:
    """Create Kimball dimensions with consistent dim_* naming."""
    op.create_table(
        "dim_date",
        sa.Column("date_key", sa.Integer(), primary_key=True),
        sa.Column("calendar_date", sa.Date(), nullable=False, unique=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="mart_dw",
    )
    op.create_table(
        "dim_company",
        sa.Column("company_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("company_hk", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("company_hk", "effective_from", name="uq_dim_company_effective"),
        schema="mart_dw",
    )
    op.create_table(
        "dim_industry",
        sa.Column("industry_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("industry_hk", sa.Text(), nullable=False),
        sa.Column("taxonomy", sa.Text(), nullable=False),
        sa.Column("industry_code", sa.Text(), nullable=False),
        sa.Column("industry_name", sa.Text()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="mart_dw",
    )
    op.create_table(
        "dim_source",
        sa.Column("source_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_hk", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="mart_dw",
    )
    op.create_table(
        "dim_provider_endpoint",
        sa.Column("provider_endpoint_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider_endpoint_hk", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("capability_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="mart_dw",
    )
    op.create_table(
        "dim_document",
        sa.Column("document_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_hk", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text()),
        sa.Column("source_name", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        schema="mart_dw",
    )
    op.create_table(
        "dim_factor",
        sa.Column("factor_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("factor_code", sa.Text(), nullable=False),
        sa.Column("factor_name", sa.Text(), nullable=False),
        sa.Column("factor_group", sa.Text(), nullable=False),
        sa.Column("factor_version", sa.Text(), nullable=False),
        sa.UniqueConstraint("factor_code", "factor_version", name="uq_dim_factor_version"),
        schema="mart_dw",
    )
    op.create_table(
        "dim_run",
        sa.Column("run_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text(), nullable=False, unique=True),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("scope_version_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        schema="mart_dw",
    )
    op.create_table(
        "dim_strategy",
        sa.Column("strategy_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("strategy_version_id", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("strategy_id", "strategy_version_id", name="uq_dim_strategy_version"),
        schema="mart_dw",
    )
    op.create_table(
        "dim_backfill_campaign",
        sa.Column("backfill_campaign_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("backfill_campaign_hk", sa.Text(), nullable=False),
        sa.Column("campaign_id", sa.Text(), nullable=False, unique=True),
        sa.Column("provider_name", sa.Text()),
        sa.Column("endpoint_name", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="mart_dw",
    )


def _create_missing_kimball_facts() -> None:
    """Create Kimball facts with consistent *_fact naming."""
    _create_stock_fact("adjusted_price_fact", sa.Column("adjusted_close", sa.Numeric()), sa.Column("adjustment_factor", sa.Numeric()))
    _create_stock_fact("daily_basic_fact", sa.Column("turnover_rate", sa.Numeric()), sa.Column("pe", sa.Numeric()), sa.Column("pb", sa.Numeric()), sa.Column("total_mv", sa.Numeric()))
    _create_stock_fact("moneyflow_fact", sa.Column("net_mf_amount", sa.Numeric()), sa.Column("buy_amount", sa.Numeric()), sa.Column("sell_amount", sa.Numeric()))
    _create_stock_fact("margin_detail_fact", sa.Column("rzye", sa.Numeric()), sa.Column("rqye", sa.Numeric()), sa.Column("rzrqye", sa.Numeric()))
    _create_stock_fact("financial_statement_fact", sa.Column("report_period_key", sa.Integer()), sa.Column("statement_type", sa.Text()), sa.Column("revenue", sa.Numeric()), sa.Column("net_profit", sa.Numeric()))
    _create_stock_fact("financial_indicator_fact", sa.Column("report_period_key", sa.Integer()), sa.Column("roe", sa.Numeric()), sa.Column("gross_margin", sa.Numeric()), sa.Column("revenue_yoy", sa.Numeric()))
    _create_stock_fact("valuation_fact", sa.Column("pe", sa.Numeric()), sa.Column("pb", sa.Numeric()), sa.Column("ps", sa.Numeric()), sa.Column("market_cap", sa.Numeric()))
    _create_stock_fact("corporate_action_fact", sa.Column("action_type", sa.Text()), sa.Column("cash_amount", sa.Numeric()), sa.Column("share_ratio", sa.Numeric()))
    _create_stock_fact("limit_suspend_fact", sa.Column("limit_status", sa.Text()), sa.Column("suspend_status", sa.Text()), sa.Column("tradable", sa.Boolean()))
    _create_stock_fact("stock_pool_membership_fact", sa.Column("snapshot_id", sa.Text()), sa.Column("pool_name", sa.Text()), sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_table(
        "document_coverage_fact",
        sa.Column("fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("stock_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_stock.stock_key")),
        sa.Column("document_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_document.document_key")),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="mart_dw",
    )
    op.create_table(
        "news_sentiment_fact",
        sa.Column("fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("stock_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_stock.stock_key")),
        sa.Column("sentiment_score", sa.Numeric()),
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="mart_dw",
    )
    op.create_table(
        "data_quality_fact",
        sa.Column("fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("provider_endpoint_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_provider_endpoint.provider_endpoint_key")),
        sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity", sa.Text()),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="mart_dw",
    )


def _create_missing_app_serving_tables() -> None:
    """Create app-layer tables that serve API and dashboard views only."""
    op.create_table(
        "company_profile_page_v1",
        sa.Column("company_profile_page_id", sa.Text(), primary_key=True),
        sa.Column("security_id", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("as_of_date", sa.Date()),
        sa.Column("decision_at", sa.DateTime(timezone=True)),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "ix_company_profile_page_security",
        "company_profile_page_v1",
        ["security_id", "decision_at"],
        schema="app",
    )
    op.create_table(
        "data_freshness_panel_v1",
        sa.Column("freshness_panel_id", sa.Text(), primary_key=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("freshness_status", sa.Text(), nullable=False),
        sa.Column("latest_available_date", sa.Date()),
        sa.Column("latest_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_table(
        "backfill_status_panel_v1",
        sa.Column("backfill_status_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_table(
        "research_run_trace_v1",
        sa.Column("trace_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("scope_version_id", sa.Text()),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )


def _create_company_profile_materialized_view() -> None:
    """Create the app-facing company profile view with real legacy joins."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mart.company_profile_view")
    op.execute(
        """
        CREATE MATERIALIZED VIEW mart.company_profile_view AS
        SELECT
            s.security_id,
            s.security_id AS ts_code,
            s.symbol,
            s.name,
            s.exchange AS exchange_code,
            s.listed_at AS list_date,
            s.delisted_at AS delist_date,
            latest.analysis_snapshot_id,
            latest.scope_version_id,
            latest.decision_at,
            latest.trading_date AS as_of_date,
            latest.summary_json,
            now() AS built_at
        FROM public.securities AS s
        LEFT JOIN LATERAL (
            SELECT a.analysis_snapshot_id,
                   a.scope_version_id,
                   a.decision_at,
                   a.trading_date,
                   a.summary_json
            FROM public.analysis_snapshots AS a
            WHERE a.security_id = s.security_id
            ORDER BY a.decision_at DESC, a.created_at DESC
            LIMIT 1
        ) AS latest ON TRUE
        WHERE s.system_to IS NULL
        """
    )
    op.create_index(
        "ux_company_profile_view_security",
        "company_profile_view",
        ["security_id"],
        unique=True,
        schema="mart",
    )


def _backfill_from_legacy_tables() -> None:
    """Backfill the new layers from the existing public/source tables."""
    op.execute(
        """
        INSERT INTO raw_meta.raw_data_snapshots (
            raw_snapshot_id,
            provider_name,
            endpoint_name,
            request_params_json,
            request_params_hash,
            fetched_at,
            provider_published_at,
            available_at,
            row_count,
            raw_storage_uri,
            raw_payload_hash,
            schema_hash,
            sync_run_id,
            quality_status
        )
        SELECT
            snapshot_id,
            provider,
            endpoint_code,
            COALESCE(payload_metadata, '{}'::jsonb),
            payload_hash,
            fetched_at,
            NULL,
            COALESCE(available_at, fetched_at),
            0,
            storage_uri,
            payload_hash,
            payload_metadata->>'schema_hash',
            payload_metadata->>'sync_run_id',
            'accepted'
        FROM public.raw_data_snapshots
        ON CONFLICT (raw_snapshot_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vault.hub_security (security_hk, ts_code, exchange_code, record_source)
        SELECT security_id, security_id, exchange, 'public.securities'
        FROM public.securities
        ON CONFLICT (security_hk) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vault.hub_company (company_hk, company_name, record_source)
        SELECT 'company:' || security_id, name, 'public.securities'
        FROM public.securities
        ON CONFLICT (company_hk) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vault.link_security_company (
            link_hk,
            security_hk,
            company_hk,
            valid_from,
            valid_to,
            record_source
        )
        SELECT
            md5(security_id || '|company|' || security_id),
            security_id,
            'company:' || security_id,
            COALESCE(listed_at, DATE '1900-01-01'),
            delisted_at,
            'public.securities'
        FROM public.securities
        ON CONFLICT (link_hk) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vault.sat_security_profile (
            security_hk,
            name,
            industry,
            list_date,
            delist_date,
            hashdiff,
            valid_from,
            valid_to,
            published_at,
            available_at,
            raw_snapshot_id,
            record_source
        )
        SELECT
            security_id,
            name,
            NULL,
            listed_at,
            delisted_at,
            md5(concat_ws('|', security_id, symbol, name, exchange, listed_at::text, delisted_at::text)),
            COALESCE(system_from, now()),
            system_to,
            NULL,
            COALESCE(system_from, now()),
            COALESCE(raw_lineage_ids->>0, 'legacy:public.securities'),
            'public.securities'
        FROM public.securities
        ON CONFLICT ON CONSTRAINT uq_sat_security_profile_hashdiff DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO mart_dw.dim_stock (
            security_hk,
            ts_code,
            symbol,
            name,
            exchange_code,
            list_date,
            delist_date,
            effective_from,
            effective_to,
            is_current
        )
        SELECT
            security_id,
            security_id,
            symbol,
            name,
            exchange,
            listed_at,
            delisted_at,
            COALESCE(listed_at, DATE '1900-01-01'),
            delisted_at,
            system_to IS NULL
        FROM public.securities
        ON CONFLICT ON CONSTRAINT uq_dim_stock_effective DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO source_tushare.ods_daily_quote_raw (
            raw_snapshot_id,
            sync_run_id,
            provider_name,
            endpoint_name,
            provider_row_key,
            ts_code,
            trade_date,
            open,
            high,
            low,
            close,
            pre_close,
            change,
            pct_chg,
            vol,
            amount,
            raw_payload_json,
            raw_payload_hash,
            natural_key_hash,
            revision_hash,
            provider_published_at,
            fetched_at,
            available_at,
            load_status
        )
        SELECT
            t.raw_snapshot_id,
            t.sync_run_id,
            'tushare',
            'daily',
            t.source_row_id,
            COALESCE(t.raw_payload->>'ts_code', t.symbol),
            t.business_date,
            CASE WHEN (t.raw_payload->>'open') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'open')::numeric END,
            CASE WHEN (t.raw_payload->>'high') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'high')::numeric END,
            CASE WHEN (t.raw_payload->>'low') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'low')::numeric END,
            CASE WHEN (t.raw_payload->>'close') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'close')::numeric END,
            CASE WHEN (t.raw_payload->>'pre_close') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'pre_close')::numeric END,
            CASE WHEN (t.raw_payload->>'change') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'change')::numeric END,
            CASE WHEN (t.raw_payload->>'pct_chg') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'pct_chg')::numeric END,
            CASE WHEN (t.raw_payload->>'vol') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'vol')::numeric END,
            CASE WHEN (t.raw_payload->>'amount') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (t.raw_payload->>'amount')::numeric END,
            t.raw_payload,
            t.revision_hash,
            t.natural_key_hash,
            t.revision_hash,
            t.published_at,
            t.fetched_at,
            t.available_at,
            t.quality_status
        FROM source_tushare.ts_daily AS t
        WHERE t.raw_snapshot_id IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM raw_meta.raw_data_snapshots AS r
              WHERE r.raw_snapshot_id = t.raw_snapshot_id
          )
        ON CONFLICT ON CONSTRAINT uq_source_tushare_ods_daily_quote_raw_revision DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO mart_dw.daily_market_fact (
            date_key,
            stock_key,
            open,
            high,
            low,
            close,
            volume,
            amount,
            available_at,
            raw_snapshot_id,
            pit_security_day_ref
        )
        SELECT
            to_char(q.trade_date, 'YYYYMMDD')::integer,
            ds.stock_key,
            q.open,
            q.high,
            q.low,
            q.close,
            q.vol,
            q.amount,
            q.available_at,
            q.raw_snapshot_id,
            ds.security_hk || ':' || q.trade_date::text
        FROM source_tushare.ods_daily_quote_raw AS q
        JOIN mart_dw.dim_stock AS ds
          ON ds.security_hk = q.ts_code
          OR ds.ts_code = q.ts_code
        ON CONFLICT (date_key, stock_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO mart.factor_panel (
            as_of_date,
            ts_code,
            universe_snapshot_id,
            feature_snapshot_id,
            factor_json,
            risk_flags,
            available_at,
            built_at
        )
        SELECT
            s.trading_date,
            COALESCE(r.symbol, r.security_id),
            s.universe_snapshot_id,
            r.feature_snapshot_id,
            r.features_json,
            ARRAY(
                SELECT jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(r.quality_flags) = 'array' THEN r.quality_flags ELSE '[]'::jsonb END
                )
            ),
            s.known_at,
            r.created_at
        FROM public.quant_feature_rows AS r
        JOIN public.quant_feature_snapshots AS s
          ON s.feature_snapshot_id = r.feature_snapshot_id
        ON CONFLICT ON CONSTRAINT uq_factor_panel_snapshot DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO mart.quant_candidate_mart (
            candidate_id,
            run_id,
            as_of_date,
            ts_code,
            candidate_rank,
            composite_score,
            factor_score_json,
            feature_snapshot_id,
            universe_snapshot_id,
            risk_flags,
            evidence_required,
            created_at
        )
        SELECT
            qr.result_id,
            qr.quant_run_id,
            qr.created_at::date,
            qr.security_id,
            qr.rank_overall,
            qr.final_score,
            qr.factor_details,
            COALESCE(qis.feature_snapshot_id, qr.quant_run_id),
            COALESCE(qfs.universe_snapshot_id, qsr.input_snapshot_id),
            ARRAY(
                SELECT jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(qr.risk_flags) = 'array' THEN qr.risk_flags ELSE '[]'::jsonb END
                )
            ),
            qr.review_required,
            qr.created_at
        FROM public.quant_screen_results AS qr
        JOIN public.quant_screen_runs AS qsr
          ON qsr.quant_run_id = qr.quant_run_id
        LEFT JOIN public.quant_input_snapshots AS qis
          ON qis.snapshot_id = qsr.input_snapshot_id
        LEFT JOIN public.quant_feature_snapshots AS qfs
          ON qfs.feature_snapshot_id = qis.feature_snapshot_id
        ON CONFLICT (candidate_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO mart.stock_analysis_mart (
            analysis_id,
            run_id,
            as_of_date,
            ts_code,
            candidate_id,
            quant_summary_json,
            financial_summary_json,
            valuation_summary_json,
            evidence_summary_json,
            risk_summary_json,
            agent_review_json,
            citation_validation_status,
            data_freshness_status,
            evidence_package_id,
            source_artifact_refs,
            created_at
        )
        SELECT
            analysis_snapshot_id,
            COALESCE(quant_run_id, analysis_snapshot_id),
            trading_date,
            security_id,
            quant_result_id,
            summary_json,
            '{}'::jsonb,
            '{}'::jsonb,
            '{}'::jsonb,
            quality_flags,
            summary_json,
            'unchecked',
            CASE WHEN jsonb_array_length(quality_flags) = 0 THEN 'ok' ELSE 'needs_review' END,
            NULL,
            ARRAY[analysis_snapshot_id],
            created_at
        FROM public.analysis_snapshots
        ON CONFLICT (analysis_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app.dashboard_items_v2 (
            dashboard_item_id,
            run_id,
            ts_code,
            payload_json,
            created_at
        )
        SELECT
            item_id,
            run_id,
            symbol,
            jsonb_build_object(
                'signal_type', signal_type,
                'confidence', confidence,
                'statement', statement,
                'status', status,
                'abstain_reason', abstain_reason,
                'rejection_reasons', rejection_reasons,
                'evidence_ids', evidence_ids,
                'claim_ids', claim_ids,
                'risk_score', risk_score,
                'counter_arguments', counter_arguments
            ),
            created_at
        FROM public.dashboard_items
        ON CONFLICT (dashboard_item_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app.company_profile_page_v1 (
            company_profile_page_id,
            security_id,
            ts_code,
            name,
            as_of_date,
            decision_at,
            payload_json,
            refreshed_at
        )
        SELECT
            security_id,
            security_id,
            ts_code,
            name,
            as_of_date,
            decision_at,
            jsonb_build_object(
                'symbol', symbol,
                'exchange_code', exchange_code,
                'list_date', list_date,
                'delist_date', delist_date,
                'analysis_snapshot_id', analysis_snapshot_id,
                'summary_json', summary_json
            ),
            built_at
        FROM mart.company_profile_view
        ON CONFLICT (company_profile_page_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app.data_freshness_panel_v1 (
            freshness_panel_id,
            provider_name,
            endpoint_name,
            freshness_status,
            latest_available_date,
            latest_fetched_at,
            payload_json,
            checked_at
        )
        SELECT
            freshness_id,
            provider,
            endpoint_code,
            status,
            as_of_date,
            observed_at,
            jsonb_build_object('expected_at', expected_at, 'lag_seconds', lag_seconds),
            created_at
        FROM public.data_freshness_states
        ON CONFLICT (freshness_panel_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app.backfill_status_panel_v1 (
            backfill_status_id,
            run_id,
            provider_name,
            status,
            completed_count,
            failed_count,
            payload_json,
            updated_at
        )
        SELECT
            run_id,
            run_id,
            provider,
            status,
            completed_count,
            failed_count,
            COALESCE(error_summary, '{}'::jsonb),
            COALESCE(finished_at, started_at, created_at)
        FROM public.data_sync_runs
        ON CONFLICT (backfill_status_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO app.research_run_trace_v1 (
            trace_id,
            run_id,
            run_type,
            state,
            scope_version_id,
            payload_json,
            created_at
        )
        SELECT
            trace_id,
            run_id,
            run_type,
            state,
            scope_version_id,
            COALESCE(metadata_json, '{}'::jsonb),
            created_at
        FROM public.orchestration_runs
        ON CONFLICT (trace_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """Drop warehouse completion objects while preserving earlier v1 tables."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mart.company_profile_view")
    for schema, table in (
        ("app", "research_run_trace_v1"),
        ("app", "backfill_status_panel_v1"),
        ("app", "data_freshness_panel_v1"),
        ("app", "company_profile_page_v1"),
        ("mart_dw", "data_quality_fact"),
        ("mart_dw", "news_sentiment_fact"),
        ("mart_dw", "document_coverage_fact"),
        ("mart_dw", "stock_pool_membership_fact"),
        ("mart_dw", "limit_suspend_fact"),
        ("mart_dw", "corporate_action_fact"),
        ("mart_dw", "valuation_fact"),
        ("mart_dw", "financial_indicator_fact"),
        ("mart_dw", "financial_statement_fact"),
        ("mart_dw", "margin_detail_fact"),
        ("mart_dw", "moneyflow_fact"),
        ("mart_dw", "daily_basic_fact"),
        ("mart_dw", "adjusted_price_fact"),
        ("mart_dw", "dim_backfill_campaign"),
        ("mart_dw", "dim_strategy"),
        ("mart_dw", "dim_run"),
        ("mart_dw", "dim_factor"),
        ("mart_dw", "dim_document"),
        ("mart_dw", "dim_provider_endpoint"),
        ("mart_dw", "dim_source"),
        ("mart_dw", "dim_industry"),
        ("mart_dw", "dim_company"),
        ("mart_dw", "dim_date"),
        ("vault", "sat_document_embedding_metadata"),
        ("vault", "sat_news_article"),
        ("vault", "sat_document_text"),
        ("vault", "sat_document_metadata"),
        ("vault", "sat_corporate_action"),
        ("vault", "sat_dividend"),
        ("vault", "sat_express"),
        ("vault", "sat_forecast"),
        ("vault", "sat_financial_statement_cashflow"),
        ("vault", "sat_financial_statement_balance"),
        ("vault", "sat_financial_statement_income"),
        ("vault", "sat_suspend_status"),
        ("vault", "sat_limit_status"),
        ("vault", "sat_margin_detail"),
        ("vault", "sat_moneyflow"),
        ("vault", "sat_daily_basic"),
        ("vault", "sat_adjustment_factor"),
        ("vault", "sat_listing_status"),
        ("vault", "sat_industry_membership"),
        ("vault", "sat_identifier"),
        ("vault", "sat_security_name_history"),
        ("vault", "link_source_snapshot"),
        ("vault", "link_stock_pool_membership"),
        ("vault", "link_security_corporate_action"),
        ("vault", "link_security_financial_statement"),
        ("vault", "link_security_daily_quote"),
        ("vault", "link_security_industry"),
        ("vault", "link_security_identifier"),
        ("vault", "hub_backfill_campaign"),
        ("vault", "hub_industry"),
        ("vault", "hub_trading_calendar"),
        ("vault", "hub_statement"),
        ("vault", "hub_provider_endpoint"),
    ):
        op.drop_table(table, schema=schema)
    op.drop_column("pit_security_day", "margin_detail_sat_id", schema="vault")
    op.drop_column("pit_security_day", "moneyflow_sat_id", schema="vault")
