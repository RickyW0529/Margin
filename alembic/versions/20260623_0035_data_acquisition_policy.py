"""Add versioned rolling-window data acquisition policy.

Revision ID: 20260623_0035_data_policy
Revises: 20260623_0034_pointer_lineage
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260623_0035_data_policy"
down_revision = "20260623_0034_pointer_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create append-only policy versions used by frontend and sync planning."""
    op.create_table(
        "data_acquisition_policy_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("rolling_window_months", sa.Integer(), nullable=False),
        sa.Column("revision_lookback_days", sa.Integer(), nullable=False),
        sa.Column("financial_comparison_years", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=96), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "activation_idempotency_key",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "rolling_window_months BETWEEN 12 AND 60",
            name="ck_data_policy_rolling_window",
        ),
        sa.CheckConstraint(
            "revision_lookback_days BETWEEN 0 AND 365",
            name="ck_data_policy_revision_lookback",
        ),
        sa.CheckConstraint(
            "financial_comparison_years BETWEEN 1 AND 3",
            name="ck_data_policy_financial_comparison",
        ),
        sa.UniqueConstraint(
            "created_by",
            "create_idempotency_key",
            name="uq_data_policy_create_idempotency",
        ),
    )
    op.create_index(
        "uq_active_data_acquisition_policy",
        "data_acquisition_policy_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )


def downgrade() -> None:
    """Drop rolling-window policy versions."""
    op.drop_index(
        "uq_active_data_acquisition_policy",
        table_name="data_acquisition_policy_versions",
    )
    op.drop_table("data_acquisition_policy_versions")
