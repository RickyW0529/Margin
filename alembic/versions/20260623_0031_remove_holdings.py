"""Remove the v0.1 portfolio and holdings-monitoring schema.

Revision ID: 20260623_0031_remove_holdings
Revises: 20260623_0030_ai_delta_graph
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260623_0031_remove_holdings"
down_revision = "20260623_0030_ai_delta_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop holdings-only tables and dashboard compatibility columns."""
    op.drop_table("position_reviews")
    op.drop_table("alert_events")
    op.drop_table("position_theses")
    op.drop_table("trades")
    op.drop_table("portfolios")
    op.drop_index(
        op.f("ix_dashboard_runs_portfolio_id"),
        table_name="dashboard_runs",
    )
    op.drop_column("dashboard_runs", "portfolio_id")
    op.drop_column("dashboard_items", "portfolio_constraint_violations")


def downgrade() -> None:
    """Restore the removed v0.1 schema for rollback only."""
    op.add_column(
        "dashboard_runs",
        sa.Column("portfolio_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_dashboard_runs_portfolio_id"),
        "dashboard_runs",
        ["portfolio_id"],
    )
    op.add_column(
        "dashboard_items",
        sa.Column(
            "portfolio_constraint_violations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_table(
        "portfolios",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cash", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id"),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])
    op.create_table(
        "trades",
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("tax", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=256), nullable=True),
        sa.Column("raw_hash", sa.String(length=96), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index("ix_trades_portfolio_id", "trades", ["portfolio_id"])
    op.create_index(
        "ix_trades_portfolio_symbol_time",
        "trades",
        ["portfolio_id", "symbol", "traded_at"],
    )
    op.create_table(
        "position_theses",
        sa.Column("thesis_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=96), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("entry_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("hold_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("invalidation_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("target_horizon", postgresql.JSONB(), nullable=False),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("thesis_id"),
        sa.UniqueConstraint(
            "portfolio_id",
            "position_id",
            "version",
            name="uq_position_thesis_version",
        ),
    )
    op.create_index(
        "ix_position_theses_portfolio_position",
        "position_theses",
        ["portfolio_id", "position_id", "version"],
    )
    op.create_table(
        "alert_events",
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=96), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("alert_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("rule_name", sa.String(length=80), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("changed_thesis", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_alert_events_portfolio_id", "alert_events", ["portfolio_id"])
    op.create_index(
        "ix_alert_events_portfolio_position",
        "alert_events",
        ["portfolio_id", "position_id"],
    )
    op.create_index(
        "ix_alert_events_severity_time",
        "alert_events",
        ["severity", "triggered_at"],
    )
    op.create_table(
        "position_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=96), nullable=False),
        sa.Column("alert_id", sa.String(length=64), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("action_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alert_events.alert_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index(
        "ix_position_reviews_portfolio_id",
        "position_reviews",
        ["portfolio_id"],
    )
    op.create_index(
        "ix_position_reviews_portfolio_position",
        "position_reviews",
        ["portfolio_id", "position_id"],
    )
