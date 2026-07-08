"""Add Tushare landing tables for ML lifecycle endpoints.

Revision ID: 20260708_0050_ml_ts_land
Revises: 20260708_0049_dash_ml_wt
Create Date: 2026-07-08 12:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0050_ml_ts_land"
down_revision = "20260708_0049_dash_ml_wt"
branch_labels = None
depends_on = None

ML_TUSHARE_ENDPOINTS = (
    "moneyflow",
    "margin_detail",
    "forecast",
    "express",
    "limit_list_d",
)


def upgrade() -> None:
    """Create endpoint-specific source landing tables for ML features."""
    op.execute("CREATE SCHEMA IF NOT EXISTS source_tushare")
    for endpoint in ML_TUSHARE_ENDPOINTS:
        _create_landing_table(f"ts_{endpoint}")


def downgrade() -> None:
    """Drop ML feature endpoint landing tables."""
    for endpoint in reversed(ML_TUSHARE_ENDPOINTS):
        op.drop_index(
            f"ix_ts_{endpoint}_pending_quality",
            table_name=f"ts_{endpoint}",
            schema="source_tushare",
        )
        op.drop_index(
            f"ix_ts_{endpoint}_business_date",
            table_name=f"ts_{endpoint}",
            schema="source_tushare",
        )
        op.drop_index(
            f"ix_ts_{endpoint}_symbol_business",
            table_name=f"ts_{endpoint}",
            schema="source_tushare",
        )
        op.drop_table(f"ts_{endpoint}", schema="source_tushare")


def _create_landing_table(table_name: str) -> None:
    """Create one generic Tushare source landing table."""
    op.create_table(
        table_name,
        sa.Column("source_row_id", sa.String(length=72), primary_key=True),
        sa.Column("natural_key_hash", sa.String(length=80), nullable=False),
        sa.Column("revision_hash", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_partition", sa.String(length=16), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("raw_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("sync_run_id", sa.String(length=64), nullable=False),
        sa.Column(
            "quality_status",
            sa.String(length=24),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_snapshot_id"],
            ["public.raw_data_snapshots.snapshot_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["public.data_sync_runs.run_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "natural_key_hash",
            "revision_hash",
            name=f"uq_{table_name}_natural_revision",
        ),
        sa.CheckConstraint(
            "quality_status IN ('pending', 'accepted', 'quarantined', 'rejected')",
            name=f"ck_{table_name}_quality_status",
        ),
        schema="source_tushare",
    )
    op.create_index(
        f"ix_{table_name}_symbol_business",
        table_name,
        ["symbol", "business_date"],
        schema="source_tushare",
    )
    op.create_index(
        f"ix_{table_name}_business_date",
        table_name,
        ["business_date"],
        schema="source_tushare",
    )
    op.create_index(
        f"ix_{table_name}_pending_quality",
        table_name,
        ["fetched_at", "source_row_id"],
        schema="source_tushare",
        postgresql_where=sa.text("quality_status = 'pending'"),
    )
