"""Add ML weight fields to dashboard items.

Revision ID: 20260708_0049_dash_ml_wt
Revises: 20260707_0048_agent_sched
Create Date: 2026-07-08 11:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0049_dash_ml_wt"
down_revision = "20260707_0048_agent_sched"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Add non-destructive ML portfolio projection fields."""
    op.add_column(
        "dashboard_items",
        sa.Column("target_weight", sa.Float(), nullable=True),
    )
    op.add_column(
        "dashboard_items",
        sa.Column("adjusted_weight", sa.Float(), nullable=True),
    )
    op.add_column(
        "dashboard_items",
        sa.Column(
            "agent_adjustment",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("dashboard_items", "agent_adjustment", server_default=None)


def downgrade() -> None:
    """Remove ML portfolio projection fields."""
    op.drop_column("dashboard_items", "agent_adjustment")
    op.drop_column("dashboard_items", "adjusted_weight")
    op.drop_column("dashboard_items", "target_weight")
