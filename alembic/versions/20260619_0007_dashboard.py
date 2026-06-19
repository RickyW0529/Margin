"""Add module 08 research candidate dashboard tables.

Revision ID: 20260619_0007_dashboard
Revises: 20260619_0006_strategy
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260619_0007_dashboard"
down_revision: str | None = "20260619_0006_strategy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create module 08 dashboard run, item, and feedback tables."""
    op.create_table(
        "dashboard_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=True),
        sa.Column("universe", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=4096), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("published_count", sa.Integer(), nullable=False),
        sa.Column("abstained_count", sa.Integer(), nullable=False),
        sa.Column("aborted_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        op.f("ix_dashboard_runs_strategy_id"),
        "dashboard_runs",
        ["strategy_id"],
    )
    op.create_index(
        op.f("ix_dashboard_runs_portfolio_id"),
        "dashboard_runs",
        ["portfolio_id"],
    )

    op.create_table(
        "dashboard_items",
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("statement", sa.String(length=4096), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("abstain_reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "rejection_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "claim_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column(
            "counter_arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "portfolio_constraint_violations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["dashboard_runs.run_id"]),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index(
        op.f("ix_dashboard_items_run_id"),
        "dashboard_items",
        ["run_id"],
    )
    op.create_index(
        op.f("ix_dashboard_items_symbol"),
        "dashboard_items",
        ["symbol"],
    )
    op.create_index(
        op.f("ix_dashboard_items_status"),
        "dashboard_items",
        ["status"],
    )

    op.create_table(
        "dashboard_feedback",
        sa.Column("feedback_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("feedback_type", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.String(length=4096), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("feedback_id"),
    )
    op.create_index(
        op.f("ix_dashboard_feedback_item_id"),
        "dashboard_feedback",
        ["item_id"],
    )


def downgrade() -> None:
    """Drop module 08 dashboard tables."""
    op.drop_index(
        op.f("ix_dashboard_feedback_item_id"),
        table_name="dashboard_feedback",
    )
    op.drop_table("dashboard_feedback")
    op.drop_index(op.f("ix_dashboard_items_status"), table_name="dashboard_items")
    op.drop_index(op.f("ix_dashboard_items_symbol"), table_name="dashboard_items")
    op.drop_index(op.f("ix_dashboard_items_run_id"), table_name="dashboard_items")
    op.drop_table("dashboard_items")
    op.drop_index(op.f("ix_dashboard_runs_portfolio_id"), table_name="dashboard_runs")
    op.drop_index(op.f("ix_dashboard_runs_strategy_id"), table_name="dashboard_runs")
    op.drop_table("dashboard_runs")
