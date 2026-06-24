"""Exclude delisting-transition names from the company-pool serving view.

Revision ID: 20260623_0039_pool_delist
Revises: 20260623_0038_pool_tushare_gate
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

revision = "20260623_0039_pool_delist"
down_revision = "20260623_0038_pool_tushare_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reject current ST and delisting-transition names at the DB view layer."""
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
          AND COALESCE(latest.raw_payload ->> 'name', s.name)
              !~ '^退市'
        """
    )


def downgrade() -> None:
    """Restore the v0.3 Tushare-gated view without delisting-name filtering."""
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
