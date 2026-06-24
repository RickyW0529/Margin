"""Add a covering index for quant indicator history reads.

Revision ID: 20260624_0040_fact_hist_idx
Revises: 20260623_0039_pool_delist
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

revision = "20260624_0040_fact_hist_idx"
down_revision = "20260623_0039_pool_delist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Index PIT indicator history queries used by QuantInput construction."""
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_indicator_facts_quant_history_cover
        ON standardized_indicator_facts (
            security_id,
            indicator_id,
            event_at,
            available_at
        )
        INCLUDE (fact_id, numeric_value)
        WHERE numeric_value IS NOT NULL
        """
    )


def downgrade() -> None:
    """Drop the quant indicator history covering index."""
    op.execute("DROP INDEX IF EXISTS ix_indicator_facts_quant_history_cover")
