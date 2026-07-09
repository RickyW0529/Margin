"""Document ContextPack ownership and add lookup helpers.

Revision ID: 20260709_0065_context_pack
Revises: 20260709_0064_secret_idempotency
Create Date: 2026-07-09 23:30:00

ContextPack structured rows in ``agent.context_packs`` are the source of truth.
Runtime artifact table ``agent_runtime_artifacts`` (or equivalent) no longer
receives mirrored context_pack payloads on write. This migration adds a partial
comment index to make pack lookups by run explicit for operators.
"""

from __future__ import annotations

from alembic import op

revision = "20260709_0065_context_pack"
down_revision = "20260709_0064_secret_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Mark agent.context_packs as the owned structured context surface."""
    op.execute(
        """
        COMMENT ON TABLE agent.context_packs IS
        'Source of truth for structured ContextPack JSON; runtime artifact store '
        'must not dual-write pack payloads (reconstruct via ContextPersistence).'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_context_packs_run_purpose
        ON agent.context_packs (run_id, scope)
        """
    )


def downgrade() -> None:
    """Drop the ownership helper index."""
    op.execute("DROP INDEX IF EXISTS agent.ix_context_packs_run_purpose")
    op.execute("COMMENT ON TABLE agent.context_packs IS NULL")
