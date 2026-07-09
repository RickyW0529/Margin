"""Add v1 Data Vault and PIT tables.

Revision ID: 20260708_0055_vault_pit_tables
Revises: 20260708_0054_raw_ods_landing
Create Date: 2026-07-09 00:05:00
"""

from __future__ import annotations

# ruff: noqa: E501
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0055_vault_pit"
down_revision = "20260708_0054_raw_ods"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Process _jsonb.

    Returns:
        postgresql.JSONB: Return value.
    """
    return postgresql.JSONB(astext_type=sa.Text())


def _text_array() -> postgresql.ARRAY:
    """Process _text_array.

    Returns:
        postgresql.ARRAY: Return value.
    """
    return postgresql.ARRAY(sa.Text())


def upgrade() -> None:
    """Create core Data Vault hubs, links, satellites, and PIT tables."""
    op.create_table(
        "hub_security",
        sa.Column("security_hk", sa.Text(), primary_key=True),
        sa.Column("ts_code", sa.Text(), nullable=False, unique=True),
        sa.Column("exchange_code", sa.Text()),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "hub_company",
        sa.Column("company_hk", sa.Text(), primary_key=True),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "hub_source",
        sa.Column("source_hk", sa.Text(), primary_key=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "hub_document",
        sa.Column("document_hk", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_company",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("company_hk", sa.Text(), sa.ForeignKey("vault.hub_company.company_hk"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "link_security_document",
        sa.Column("link_hk", sa.Text(), primary_key=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("document_hk", sa.Text(), sa.ForeignKey("vault.hub_document.document_hk"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("record_source", sa.Text(), nullable=False),
        schema="vault",
    )
    op.create_table(
        "sat_security_profile",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("industry", sa.Text()),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("hashdiff", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("security_hk", "hashdiff", name="uq_sat_security_profile_hashdiff"),
        schema="vault",
    )
    op.create_table(
        "sat_daily_quote",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric()),
        sa.Column("high", sa.Numeric()),
        sa.Column("low", sa.Numeric()),
        sa.Column("close", sa.Numeric()),
        sa.Column("pre_close", sa.Numeric()),
        sa.Column("volume", sa.Numeric()),
        sa.Column("amount", sa.Numeric()),
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
        sa.UniqueConstraint("security_hk", "trade_date", "hashdiff", name="uq_sat_daily_quote_hashdiff"),
        schema="vault",
    )
    op.create_index(
        "ix_sat_daily_quote_pit",
        "sat_daily_quote",
        ["security_hk", "trade_date", "available_at"],
        schema="vault",
    )
    op.create_table(
        "sat_financial_indicator",
        sa.Column("sat_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_hk", sa.Text(), sa.ForeignKey("vault.hub_security.security_hk"), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("statement_type", sa.Text()),
        sa.Column("roe", sa.Numeric()),
        sa.Column("roa", sa.Numeric()),
        sa.Column("gross_margin", sa.Numeric()),
        sa.Column("net_margin", sa.Numeric()),
        sa.Column("debt_to_assets", sa.Numeric()),
        sa.Column("revenue_yoy", sa.Numeric()),
        sa.Column("profit_yoy", sa.Numeric()),
        sa.Column("hashdiff", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("system_to", sa.DateTime(timezone=True)),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("record_source", sa.Text(), nullable=False),
        sa.Column("load_dts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("security_hk", "report_period", "statement_type", "hashdiff", name="uq_sat_financial_indicator_hashdiff"),
        schema="vault",
    )
    op.create_index(
        "ix_sat_financial_indicator_pit",
        "sat_financial_indicator",
        ["security_hk", "report_period", "available_at"],
        schema="vault",
    )
    op.create_table(
        "pit_security_day",
        sa.Column("security_hk", sa.Text(), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("daily_quote_sat_id", sa.BigInteger()),
        sa.Column("adjustment_factor_sat_id", sa.BigInteger()),
        sa.Column("daily_basic_sat_id", sa.BigInteger()),
        sa.Column("limit_status_sat_id", sa.BigInteger()),
        sa.Column("suspend_status_sat_id", sa.BigInteger()),
        sa.Column("industry_sat_id", sa.BigInteger()),
        sa.Column("listing_status_sat_id", sa.BigInteger()),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("security_hk", "decision_date"),
        schema="vault",
    )
    op.create_table(
        "pit_financial_statement",
        sa.Column("security_hk", sa.Text(), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("latest_report_period", sa.Date()),
        sa.Column("income_sat_id", sa.BigInteger()),
        sa.Column("balance_sat_id", sa.BigInteger()),
        sa.Column("cashflow_sat_id", sa.BigInteger()),
        sa.Column("indicator_sat_id", sa.BigInteger()),
        sa.Column("forecast_sat_id", sa.BigInteger()),
        sa.Column("express_sat_id", sa.BigInteger()),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("security_hk", "decision_date"),
        schema="vault",
    )
    op.create_table(
        "pit_stock_pool_snapshot",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column("pool_name", sa.Text(), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("security_hks", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("exclusion_rules_json", _jsonb(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="vault",
    )


def downgrade() -> None:
    """Drop only tables introduced by this revision."""
    for table in (
        "pit_stock_pool_snapshot",
        "pit_financial_statement",
        "pit_security_day",
        "sat_financial_indicator",
        "sat_daily_quote",
        "sat_security_profile",
        "link_security_document",
        "link_security_company",
        "hub_document",
        "hub_source",
        "hub_company",
        "hub_security",
    ):
        op.drop_table(table, schema="vault")
