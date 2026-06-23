"""Add immutable input reference to orchestration step events.

Revision ID: 20260622_0020_step_input
Revises: 20260622_0019_capacity
Create Date: 2026-06-22 22:30:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0020_step_input"
down_revision = "20260622_0019_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.add_column(
        "orchestration_step_attempts",
        sa.Column("input_ref", sa.String(length=256)),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_column("orchestration_step_attempts", "input_ref")
