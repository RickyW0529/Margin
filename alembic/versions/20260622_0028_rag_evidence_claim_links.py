"""Add v0.2 evidence claim status and link rank.

Revision ID: 20260622_0028_rag_evidence_links
Revises: 20260622_0027_rag_evidence
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260622_0028_rag_evidence_links"
down_revision = "20260622_0027_rag_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply v0.2 claim status and link rank columns."""
    op.add_column(
        "evidence_claims",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="unsupported",
        ),
    )
    op.alter_column("evidence_claims", "status", server_default=None)
    op.add_column(
        "claim_evidence_links",
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("claim_evidence_links", "rank", server_default=None)


def downgrade() -> None:
    """Revert v0.2 claim status and link rank columns."""
    op.drop_column("claim_evidence_links", "rank")
    op.drop_column("evidence_claims", "status")
