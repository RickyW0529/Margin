"""Add persisted agent chat sessions and messages.

Revision ID: 20260708_0051_agent_chat
Revises: 20260708_0050_ml_ts_land
Create Date: 2026-07-08 19:02:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0051_agent_chat"
down_revision = "20260708_0050_ml_ts_land"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create persisted user-facing Agent chat tables."""
    op.create_table(
        "agent_chat_sessions",
        sa.Column("session_id", sa.String(length=96), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("universe", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_chat_sessions_updated",
        "agent_chat_sessions",
        ["updated_at"],
    )
    op.create_table(
        "agent_chat_messages",
        sa.Column("message_id", sa.String(length=96), primary_key=True),
        sa.Column("session_id", sa.String(length=96), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=64)),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_chat_messages_session_created",
        "agent_chat_messages",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_agent_chat_messages_run",
        "agent_chat_messages",
        ["run_id"],
    )


def downgrade() -> None:
    """Drop persisted user-facing Agent chat tables."""
    op.drop_index("ix_agent_chat_messages_run", table_name="agent_chat_messages")
    op.drop_index(
        "ix_agent_chat_messages_session_created",
        table_name="agent_chat_messages",
    )
    op.drop_table("agent_chat_messages")
    op.drop_index("ix_agent_chat_sessions_updated", table_name="agent_chat_sessions")
    op.drop_table("agent_chat_sessions")
