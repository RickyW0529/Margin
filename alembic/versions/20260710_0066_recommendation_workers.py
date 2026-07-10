"""Persist durable recommendation worker artifacts.

Revision ID: 20260710_0066_recommendation
Revises: 20260709_0065_context_pack
Create Date: 2026-07-10 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260710_0066_recommendation"
down_revision = "20260709_0065_context_pack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the immutable worker-artifact boundary."""
    op.create_table(
        "recommendation_worker_artifacts",
        sa.Column("artifact_id", sa.String(length=96), nullable=False),
        sa.Column("orchestration_run_id", sa.String(length=64), nullable=False),
        sa.Column("worker_name", sa.String(length=96), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
        sa.UniqueConstraint(
            "orchestration_run_id",
            "worker_name",
            name="uq_recommendation_worker_artifacts_run_worker",
        ),
    )
    op.create_index(
        "ix_recommendation_worker_artifacts_scope_decision",
        "recommendation_worker_artifacts",
        ["scope_version_id", "decision_at"],
    )


def downgrade() -> None:
    """Drop recommendation worker artifacts."""
    op.drop_index(
        "ix_recommendation_worker_artifacts_scope_decision",
        table_name="recommendation_worker_artifacts",
    )
    op.drop_table("recommendation_worker_artifacts")
