"""Add effective assessment pointer freshness fields.

Revision ID: 20260622_0024_assessment_pointer
Revises: 20260622_0023_quant_ranks
Create Date: 2026-06-22 23:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0024_assessment_pointer"
down_revision = "20260622_0023_quant_ranks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.add_column(
        "effective_assessment_pointers",
        sa.Column(
            "assessment_freshness",
            sa.String(length=32),
            nullable=False,
            server_default="current",
        ),
    )
    op.add_column(
        "effective_assessment_pointers",
        sa.Column("stale_reason", sa.String(length=128)),
    )
    op.add_column(
        "effective_assessment_pointers",
        sa.Column("last_successful_data_check_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "effective_assessment_pointers",
        sa.Column("last_successful_news_check_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_column("effective_assessment_pointers", "last_successful_news_check_at")
    op.drop_column("effective_assessment_pointers", "last_successful_data_check_at")
    op.drop_column("effective_assessment_pointers", "stale_reason")
    op.drop_column("effective_assessment_pointers", "assessment_freshness")
