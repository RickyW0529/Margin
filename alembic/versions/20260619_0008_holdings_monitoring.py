"""Add module 09 holdings monitoring tables.

Revision ID: 20260619_0008_monitoring
Revises: 20260619_0007_dashboard
Create Date: 2026-06-19 16:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260619_0008_monitoring"
down_revision: str | None = "20260619_0007_dashboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create holdings monitoring alert and review tables."""
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
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_thesis", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index(
        "ix_alert_events_portfolio_id",
        "alert_events",
        ["portfolio_id"],
    )
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


def downgrade() -> None:
    """Drop holdings monitoring tables."""
    op.drop_index("ix_position_reviews_portfolio_position", table_name="position_reviews")
    op.drop_index("ix_position_reviews_portfolio_id", table_name="position_reviews")
    op.drop_table("position_reviews")
    op.drop_index("ix_alert_events_severity_time", table_name="alert_events")
    op.drop_index("ix_alert_events_portfolio_position", table_name="alert_events")
    op.drop_index("ix_alert_events_portfolio_id", table_name="alert_events")
    op.drop_table("alert_events")
