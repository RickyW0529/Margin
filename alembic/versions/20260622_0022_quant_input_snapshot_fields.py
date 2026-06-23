"""Add frozen quant input snapshot lineage fields.

Revision ID: 20260622_0022_quant_input
Revises: 20260622_0021_valuation
Create Date: 2026-06-22 22:35:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0022_quant_input"
down_revision = "20260622_0021_valuation"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """jsonb."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """upgrade."""
    op.add_column(
        "quant_input_snapshots",
        sa.Column("quant_feature_set_version_id", sa.String(length=64)),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("user_indicator_view_version_id", sa.String(length=64)),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("market_window_start", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("market_window_end", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("quality_flags", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column(
            "freshness_flags",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column(
            "pit_validation_errors",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("corporate_action_adjustment_version", sa.String(length=64)),
    )
    op.add_column(
        "quant_input_snapshots",
        sa.Column("industry_snapshot_id", sa.String(length=96)),
    )


def downgrade() -> None:
    """downgrade."""
    for column in (
        "industry_snapshot_id",
        "corporate_action_adjustment_version",
        "pit_validation_errors",
        "freshness_flags",
        "quality_flags",
        "market_window_end",
        "market_window_start",
        "user_indicator_view_version_id",
        "quant_feature_set_version_id",
    ):
        op.drop_column("quant_input_snapshots", column)
