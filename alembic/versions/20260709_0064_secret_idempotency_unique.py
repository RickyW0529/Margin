"""Add unique index for provider secret idempotency keys.

Revision ID: 20260709_0064_secret_idempotency
Revises: 20260709_0063_platform_ops
Create Date: 2026-07-09 22:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20260709_0064_secret_idempotency"
down_revision = "20260709_0063_platform_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enforce one secret write per (provider, name, idempotency_key)."""
    op.create_index(
        "uq_provider_secret_idempotency",
        "provider_secret_versions",
        ["provider_name", "secret_name", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the secret idempotency unique index."""
    op.drop_index("uq_provider_secret_idempotency", table_name="provider_secret_versions")
