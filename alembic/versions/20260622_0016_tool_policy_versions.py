"""Add v0.2 tool policy versions table.

Revision ID: 20260622_0016_tool_policy
Revises: 20260622_0015_strategy_v02
Create Date: 2026-06-22 18:16:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0016_tool_policy"
down_revision = "20260622_0015_strategy_v02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.create_table(
        "tool_policy_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column(
            "allowed_tool_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "denied_tool_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_tool_policy_versions",
        "tool_policy_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_index("uq_active_tool_policy_versions", table_name="tool_policy_versions")
    op.drop_table("tool_policy_versions")
