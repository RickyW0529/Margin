"""Make active capacity limits unique and counters version-specific.

Revision ID: 20260622_0019_capacity
Revises: 20260622_0018_deploy_audit
Create Date: 2026-06-22 22:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0019_capacity"
down_revision = "20260622_0018_deploy_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.drop_constraint(
        "uq_provider_capacity_window",
        "provider_capacity_counters",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_provider_capacity_window",
        "provider_capacity_counters",
        ["limit_key", "limit_version_id", "window_started_at"],
    )
    op.create_index(
        "uq_active_capacity_limit_key",
        "capacity_limit_versions",
        ["limit_key"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_index(
        "uq_active_capacity_limit_key",
        table_name="capacity_limit_versions",
    )
    op.drop_constraint(
        "uq_provider_capacity_window",
        "provider_capacity_counters",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_provider_capacity_window",
        "provider_capacity_counters",
        ["limit_key", "window_started_at"],
    )
