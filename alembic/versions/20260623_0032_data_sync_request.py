"""Persist the complete data-sync request for asynchronous workers.

Revision ID: 20260623_0032_data_sync_request
Revises: 20260623_0031_remove_holdings
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260623_0032_data_sync_request"
down_revision = "20260623_0031_remove_holdings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the immutable request payload used by background sync workers."""
    op.add_column(
        "data_sync_runs",
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove the persisted request payload."""
    op.drop_column("data_sync_runs", "request_payload")
