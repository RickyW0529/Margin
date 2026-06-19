"""Add append-only module 06 research snapshots.

Revision ID: 20260619_0005_research
Revises: 20260618_0004_evidence
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260619_0005_research"
down_revision: str | None = "20260618_0004_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the append-only research snapshot table."""
    op.create_table(
        "research_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_state", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("output_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        op.f("ix_research_snapshots_run_id"),
        "research_snapshots",
        ["run_id"],
    )
    op.create_index(
        "ix_research_snapshots_run_created",
        "research_snapshots",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    """Drop the module 06 research snapshot table."""
    op.drop_index(
        "ix_research_snapshots_run_created",
        table_name="research_snapshots",
    )
    op.drop_index(
        op.f("ix_research_snapshots_run_id"),
        table_name="research_snapshots",
    )
    op.drop_table("research_snapshots")
