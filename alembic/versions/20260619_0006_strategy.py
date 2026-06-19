"""Add module 07 strategy configuration tables.

Revision ID: 20260619_0006_strategy
Revises: 20260619_0005_research
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260619_0006_strategy"
down_revision: str | None = "20260619_0005_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create strategy profile and immutable version tables."""
    op.create_table(
        "strategy_profiles",
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("active_version_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("strategy_id"),
    )
    op.create_index(
        op.f("ix_strategy_profiles_owner_id"),
        "strategy_profiles",
        ["owner_id"],
    )

    op.create_table(
        "strategy_versions",
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=4096), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "prompt_layers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column(
            "sandbox_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy_profiles.strategy_id"],
        ),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index(
        op.f("ix_strategy_versions_strategy_id"),
        "strategy_versions",
        ["strategy_id"],
    )


def downgrade() -> None:
    """Drop module 07 strategy configuration tables."""
    op.drop_index(
        op.f("ix_strategy_versions_strategy_id"),
        table_name="strategy_versions",
    )
    op.drop_table("strategy_versions")
    op.drop_index(
        op.f("ix_strategy_profiles_owner_id"),
        table_name="strategy_profiles",
    )
    op.drop_table("strategy_profiles")
