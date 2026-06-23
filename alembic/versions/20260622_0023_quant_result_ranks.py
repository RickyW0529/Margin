"""Add quant result rank columns.

Revision ID: 20260622_0023_quant_ranks
Revises: 20260622_0022_quant_input
Create Date: 2026-06-22 22:50:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0023_quant_ranks"
down_revision = "20260622_0022_quant_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.add_column("quant_screen_results", sa.Column("rank_overall", sa.Integer()))
    op.add_column("quant_screen_results", sa.Column("rank_in_industry", sa.Integer()))


def downgrade() -> None:
    """downgrade."""
    op.drop_column("quant_screen_results", "rank_in_industry")
    op.drop_column("quant_screen_results", "rank_overall")
