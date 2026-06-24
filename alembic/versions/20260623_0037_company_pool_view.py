"""Add the non-ST All-A company-pool view and immutable snapshots.

Revision ID: 20260623_0037_company_pool
Revises: 20260623_0036_tushare_source
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260623_0037_company_pool"
down_revision = "20260623_0036_tushare_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the serving view, immutable snapshots, and measured access paths."""
    op.create_index(
        "ix_securities_active_stock_pool",
        "securities",
        ["security_type", "security_id"],
        postgresql_where=sa.text(
            "system_to IS NULL AND delisted_at IS NULL AND security_type = 'stock'"
        ),
    )
    op.execute(
        """
        CREATE VIEW company_pool_current_non_st AS
        SELECT
            s.security_id,
            s.symbol,
            s.name,
            s.exchange,
            s.listed_at,
            industry.industry_code,
            industry.industry_name
        FROM securities AS s
        LEFT JOIN LATERAL (
            SELECT m.industry_code, m.industry_name
            FROM security_industry_memberships AS m
            WHERE m.security_id = s.security_id
              AND m.system_to IS NULL
            ORDER BY m.valid_from DESC, m.system_from DESC
            LIMIT 1
        ) AS industry ON TRUE
        WHERE s.system_to IS NULL
          AND s.delisted_at IS NULL
          AND s.security_type = 'stock'
          AND upper(s.name) !~ '^(S\\*ST|\\*ST|ST)'
        """
    )
    op.create_table(
        "company_pool_snapshots",
        sa.Column("snapshot_id", sa.String(length=72), primary_key=True),
        sa.Column("pool_code", sa.String(length=64), nullable=False),
        sa.Column("source_run_id", sa.String(length=64), nullable=False),
        sa.Column("business_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(), nullable=False),
        sa.Column("input_hash", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["data_sync_runs.run_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "pool_code",
            "source_run_id",
            name="uq_company_pool_source_run",
        ),
        sa.CheckConstraint(
            "member_count >= 0",
            name="ck_company_pool_member_count",
        ),
    )
    op.create_index(
        "ix_company_pool_latest",
        "company_pool_snapshots",
        ["pool_code", "business_at", "created_at"],
    )
    op.create_table(
        "company_pool_members",
        sa.Column("membership_id", sa.String(length=72), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=72), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("industry_code", sa.String(length=64), nullable=True),
        sa.Column("industry_name", sa.Text(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("data_status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["company_pool_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.security_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "security_id",
            name="uq_company_pool_member",
        ),
    )
    op.create_index(
        "ix_company_pool_members_included",
        "company_pool_members",
        ["snapshot_id", "security_id"],
        postgresql_where=sa.text("included = true"),
    )
    op.create_index(
        "ix_company_pool_members_security",
        "company_pool_members",
        ["security_id", "snapshot_id"],
    )


def downgrade() -> None:
    """Drop company-pool snapshots, serving view, and indexes."""
    op.drop_index(
        "ix_company_pool_members_security",
        table_name="company_pool_members",
    )
    op.drop_index(
        "ix_company_pool_members_included",
        table_name="company_pool_members",
    )
    op.drop_table("company_pool_members")
    op.drop_index(
        "ix_company_pool_latest",
        table_name="company_pool_snapshots",
    )
    op.drop_table("company_pool_snapshots")
    op.execute("DROP VIEW IF EXISTS company_pool_current_non_st")
    op.drop_index(
        "ix_securities_active_stock_pool",
        table_name="securities",
    )
