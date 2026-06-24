"""Add the independent AKShare source-system table skeleton.

Revision ID: 20260624_0041_akshare_source
Revises: 20260624_0040_fact_hist_idx
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260624_0041_akshare_source"
down_revision = "20260624_0040_fact_hist_idx"
branch_labels = None
depends_on = None

AKSHARE_ENDPOINTS = (
    "stock_zh_a_spot_em",
    "stock_zh_a_hist",
    "stock_balance_sheet_by_report_em",
    "stock_value_em",
    "index_stock_cons_csindex",
)


def upgrade() -> None:
    """Create AKShare endpoint-specific landing tables for future ingestion."""
    op.execute("CREATE SCHEMA IF NOT EXISTS source_akshare")
    for endpoint in AKSHARE_ENDPOINTS:
        table_name = f"ak_{endpoint}"
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
            sa.Column("source_partition", sa.String(length=32), nullable=False),
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
            schema="source_akshare",
        )
        op.create_index(
            f"ix_{table_name}_symbol_business",
            table_name,
            ["symbol", "business_date"],
            schema="source_akshare",
        )
        op.create_index(
            f"ix_{table_name}_business_date",
            table_name,
            ["business_date"],
            schema="source_akshare",
        )
        op.create_index(
            f"ix_{table_name}_pending_quality",
            table_name,
            ["fetched_at", "source_row_id"],
            schema="source_akshare",
            postgresql_where=sa.text("quality_status = 'pending'"),
        )


def downgrade() -> None:
    """Drop the AKShare independent source schema."""
    op.execute("DROP SCHEMA IF EXISTS source_akshare CASCADE")
