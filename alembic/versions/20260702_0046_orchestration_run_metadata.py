"""Add orchestration run metadata.

Revision ID: 20260702_0046_run_metadata
Revises: 20260629_0045_agentic_news
Create Date: 2026-07-02 00:46:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260702_0046_run_metadata"
down_revision = "20260629_0045_agentic_news"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Add JSON metadata to durable orchestration runs."""
    op.add_column(
        "orchestration_runs",
        sa.Column(
            "metadata_json",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove JSON metadata from durable orchestration runs."""
    op.drop_column("orchestration_runs", "metadata_json")
