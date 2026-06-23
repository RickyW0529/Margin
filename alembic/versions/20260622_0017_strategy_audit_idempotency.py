"""Add strategy config audit idempotency constraint.

Revision ID: 20260622_0017_config_audit
Revises: 20260622_0016_tool_policy
Create Date: 2026-06-22 21:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0017_config_audit"
down_revision = "20260622_0016_tool_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.create_index(
        "uq_strategy_config_audit_idempotency",
        "strategy_config_audits",
        ["actor_id", "action", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_index(
        "uq_strategy_config_audit_idempotency",
        table_name="strategy_config_audits",
    )
