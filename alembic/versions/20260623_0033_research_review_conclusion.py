"""Persist structured AI review conclusion fields.

Revision ID: 20260623_0033_review_conclusion
Revises: 20260623_0032_data_sync_request
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260623_0033_review_conclusion"
down_revision = "20260623_0032_data_sync_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the structured conclusion emitted by the production graph."""
    op.add_column(
        "research_delta_reviews",
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "research_delta_reviews",
        sa.Column(
            "conclusion",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "research_delta_reviews",
        sa.Column(
            "valuation_view",
            sa.String(length=32),
            nullable=False,
            server_default="uncertain",
        ),
    )


def downgrade() -> None:
    """Remove structured review conclusion fields."""
    op.drop_column("research_delta_reviews", "valuation_view")
    op.drop_column("research_delta_reviews", "conclusion")
    op.drop_column("research_delta_reviews", "confidence")
