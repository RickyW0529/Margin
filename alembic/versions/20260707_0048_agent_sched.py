"""Add v0.4 agent runtime schedule table.

Revision ID: 20260707_0048_agent_sched
Revises: 20260707_0047_agent_runtime
Create Date: 2026-07-07 01:18:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260707_0048_agent_sched"
down_revision = "20260707_0047_agent_runtime"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create persisted agent schedule table."""
    op.create_table(
        "agent_runtime_schedules",
        sa.Column("schedule_id", sa.String(length=96), primary_key=True),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("universe", sa.String(length=32), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_runtime_schedules_enabled_next",
        "agent_runtime_schedules",
        ["enabled", "next_run_at"],
    )


def downgrade() -> None:
    """Drop persisted agent schedule table."""
    op.drop_index(
        "ix_agent_runtime_schedules_enabled_next",
        table_name="agent_runtime_schedules",
    )
    op.drop_table("agent_runtime_schedules")
