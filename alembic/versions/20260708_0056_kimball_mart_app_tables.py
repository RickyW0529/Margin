"""Add v1 Kimball, mart, and app tables.

Revision ID: 20260708_0056_kimball_mart_app_tables
Revises: 20260708_0055_vault_pit_tables
Create Date: 2026-07-09 00:10:00
"""

from __future__ import annotations

# ruff: noqa: E501
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0056_mart_app"
down_revision = "20260708_0055_vault_pit"
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
    """Create representative Kimball, Analysis Mart, and app tables."""
    op.create_table(
        "dim_stock",
        sa.Column("stock_key", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_hk", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("exchange_code", sa.Text()),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("security_hk", "effective_from", name="uq_dim_stock_effective"),
        schema="mart_dw",
    )
    op.create_table(
        "daily_market_fact",
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("stock_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_stock.stock_key"), nullable=False),
        sa.Column("open", sa.Numeric()),
        sa.Column("high", sa.Numeric()),
        sa.Column("low", sa.Numeric()),
        sa.Column("close", sa.Numeric()),
        sa.Column("volume", sa.Numeric()),
        sa.Column("amount", sa.Numeric()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=False),
        sa.Column("pit_security_day_ref", sa.Text()),
        sa.PrimaryKeyConstraint("date_key", "stock_key"),
        schema="mart_dw",
    )
    op.create_index(
        "ix_daily_market_fact_available",
        "daily_market_fact",
        ["available_at"],
        schema="mart_dw",
    )
    op.create_table(
        "factor_fact",
        sa.Column("factor_fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("stock_key", sa.BigInteger(), sa.ForeignKey("mart_dw.dim_stock.stock_key"), nullable=False),
        sa.Column("factor_key", sa.BigInteger(), nullable=False),
        sa.Column("factor_value", sa.Numeric()),
        sa.Column("factor_version", sa.Text(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_lineage_json", _jsonb(), nullable=False),
        sa.UniqueConstraint("date_key", "stock_key", "factor_key", "factor_version", name="uq_factor_fact_version"),
        schema="mart_dw",
    )
    op.create_table(
        "factor_panel",
        sa.Column("panel_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("universe_snapshot_id", sa.Text(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Text(), nullable=False),
        sa.Column("factor_json", _jsonb(), nullable=False),
        sa.Column("risk_flags", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("as_of_date", "ts_code", "feature_snapshot_id", name="uq_factor_panel_snapshot"),
        schema="mart",
    )
    op.create_table(
        "quant_candidate_mart",
        sa.Column("candidate_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("candidate_rank", sa.Integer()),
        sa.Column("composite_score", sa.Numeric()),
        sa.Column("factor_score_json", _jsonb(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Text(), nullable=False),
        sa.Column("universe_snapshot_id", sa.Text(), nullable=False),
        sa.Column("risk_flags", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("evidence_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="mart",
    )
    op.create_index(
        "ix_quant_candidate_mart_run",
        "quant_candidate_mart",
        ["run_id"],
        schema="mart",
    )
    op.create_index(
        "ix_quant_candidate_mart_date_score",
        "quant_candidate_mart",
        ["as_of_date", "composite_score"],
        schema="mart",
    )
    op.create_table(
        "stock_analysis_mart",
        sa.Column("analysis_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Text()),
        sa.Column("quant_summary_json", _jsonb()),
        sa.Column("financial_summary_json", _jsonb()),
        sa.Column("valuation_summary_json", _jsonb()),
        sa.Column("evidence_summary_json", _jsonb()),
        sa.Column("risk_summary_json", _jsonb()),
        sa.Column("agent_review_json", _jsonb()),
        sa.Column("citation_validation_status", sa.Text(), nullable=False),
        sa.Column("data_freshness_status", sa.Text(), nullable=False),
        sa.Column("evidence_package_id", sa.Text()),
        sa.Column("source_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="mart",
    )
    op.create_table(
        "backtest_panel",
        sa.Column("panel_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("universe_member", sa.Boolean(), nullable=False),
        sa.Column("tradable", sa.Boolean(), nullable=False),
        sa.Column("adjusted_close", sa.Numeric()),
        sa.Column("next_period_return", sa.Numeric()),
        sa.Column("factor_json", _jsonb(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_snapshot_id", sa.Text(), nullable=False),
        sa.Column("universe_snapshot_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("strategy_id", "as_of_date", "ts_code", "feature_snapshot_id", name="uq_backtest_panel_feature"),
        schema="mart",
    )
    # app.dashboard_items_v2
    op.create_table(
        "dashboard_items_v2",
        sa.Column("dashboard_item_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text()),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_table(
        "agent_answer_context_v1",
        sa.Column("answer_context_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("context_pack_id", sa.Text()),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )


def downgrade() -> None:
    """Drop only tables introduced by this revision."""
    for schema, table in (
        ("app", "agent_answer_context_v1"),
        ("app", "dashboard_items_v2"),
        ("mart", "backtest_panel"),
        ("mart", "stock_analysis_mart"),
        ("mart", "quant_candidate_mart"),
        ("mart", "factor_panel"),
        ("mart_dw", "factor_fact"),
        ("mart_dw", "daily_market_fact"),
        ("mart_dw", "dim_stock"),
    ):
        op.drop_table(table, schema=schema)
