"""Bind company pool membership to accepted current Tushare master data.

Revision ID: 20260623_0038_pool_tushare_gate
Revises: 20260623_0037_company_pool
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260623_0038_pool_tushare_gate"
down_revision = "20260623_0037_company_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Use accepted Tushare stock-basic rows as the current membership gate."""
    op.create_index(
        "ix_ts_stock_basic_accepted_symbol",
        "ts_stock_basic",
        ["symbol", "fetched_at"],
        schema="source_tushare",
        postgresql_where=sa.text("quality_status = 'accepted'"),
    )
    op.execute("DROP VIEW company_pool_current_non_st")
    op.execute(
        r"""
        CREATE VIEW company_pool_current_non_st AS
        WITH latest_tushare AS (
            SELECT DISTINCT ON (source.symbol)
                source.symbol,
                source.raw_payload,
                source.fetched_at,
                source.created_at
            FROM source_tushare.ts_stock_basic AS source
            WHERE source.quality_status = 'accepted'
            ORDER BY source.symbol, source.fetched_at DESC, source.created_at DESC
        )
        SELECT
            s.security_id,
            s.symbol,
            COALESCE(latest.raw_payload ->> 'name', s.name) AS name,
            s.exchange,
            s.listed_at,
            COALESCE(
                latest.raw_payload ->> 'industry',
                industry.industry_code
            ) AS industry_code,
            COALESCE(
                latest.raw_payload ->> 'industry',
                industry.industry_name
            ) AS industry_name
        FROM latest_tushare AS latest
        JOIN securities AS s
          ON s.security_id = latest.symbol
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
          AND upper(COALESCE(latest.raw_payload ->> 'name', s.name))
              !~ '^(S\*ST|\*ST|ST)'
        """
    )


def downgrade() -> None:
    """Restore the warehouse-only view definition."""
    op.execute("DROP VIEW company_pool_current_non_st")
    op.execute(
        r"""
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
          AND upper(s.name) !~ '^(S\*ST|\*ST|ST)'
        """
    )
    op.drop_index(
        "ix_ts_stock_basic_accepted_symbol",
        table_name="ts_stock_basic",
        schema="source_tushare",
    )
