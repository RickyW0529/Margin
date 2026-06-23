"""Persist structured evidence locator details.

Revision ID: 20260622_0029_evidence_locator
Revises: 20260622_0028_rag_evidence_links
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0029_evidence_locator"
down_revision = "20260622_0028_rag_evidence_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add replayable bbox, DOM, and table-column locator fields."""
    op.add_column(
        "evidence_records",
        sa.Column(
            "bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "evidence_records",
        sa.Column("dom_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "evidence_records",
        sa.Column("column_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """Remove structured locator detail fields."""
    op.drop_column("evidence_records", "column_id")
    op.drop_column("evidence_records", "dom_path")
    op.drop_column("evidence_records", "bbox")
