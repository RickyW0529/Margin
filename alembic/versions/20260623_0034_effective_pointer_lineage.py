"""Correct effective assessment pointer lineage naming.

Revision ID: 20260623_0034_pointer_lineage
Revises: 20260623_0033_review_conclusion
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision = "20260623_0034_pointer_lineage"
down_revision = "20260623_0033_review_conclusion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename the lineage field to describe the value it stores."""
    op.alter_column(
        "effective_assessment_pointers",
        "replaced_by_assessment_id",
        new_column_name="previous_assessment_id",
    )


def downgrade() -> None:
    """Restore the legacy, ambiguous column name."""
    op.alter_column(
        "effective_assessment_pointers",
        "previous_assessment_id",
        new_column_name="replaced_by_assessment_id",
    )
