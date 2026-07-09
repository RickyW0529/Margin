"""Add formal ToolGateway audit tables.

Revision ID: 20260709_0061_tool_audit
Revises: 20260709_0060_context
Create Date: 2026-07-09 16:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260709_0061_tool_audit"
down_revision = "20260709_0060_context"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return PostgreSQL JSONB with text astype."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create formal ToolGateway catalog and audit tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS tool")
    op.create_table(
        "tool_catalog_versions",
        sa.Column("tool_catalog_version_id", sa.Text(), primary_key=True),
        sa.Column("catalog_json", _jsonb(), nullable=False),
        sa.Column("catalog_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tool",
    )
    op.create_index(
        "ix_tool_catalog_versions_active",
        "tool_catalog_versions",
        ["is_active"],
        schema="tool",
    )

    op.create_table(
        "tool_calls",
        sa.Column("tool_call_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("caller_agent", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("input_redacted_json", _jsonb(), nullable=False),
        sa.Column("capability_token_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tool",
    )
    op.create_index("ix_tool_calls_run_task", "tool_calls", ["run_id", "task_id"], schema="tool")
    op.create_index(
        "ix_tool_calls_tool_started",
        "tool_calls",
        ["tool_name", "started_at"],
        schema="tool",
    )

    op.create_table(
        "tool_results",
        sa.Column(
            "tool_call_id",
            sa.Text(),
            sa.ForeignKey("tool.tool_calls.tool_call_id"),
            primary_key=True,
        ),
        sa.Column("output_hash", sa.Text()),
        sa.Column("output_redacted_json", _jsonb()),
        sa.Column(
            "output_artifact_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("output_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="tool",
    )

    op.create_table(
        "tool_rate_limit_buckets",
        sa.Column("bucket_id", sa.Text(), primary_key=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        schema="tool",
    )
    op.create_index(
        "ix_tool_rate_limit_tool_window",
        "tool_rate_limit_buckets",
        ["tool_name", "window_start"],
        schema="tool",
    )


def downgrade() -> None:
    """Drop formal ToolGateway catalog and audit tables."""
    op.drop_index(
        "ix_tool_rate_limit_tool_window",
        table_name="tool_rate_limit_buckets",
        schema="tool",
    )
    op.drop_table("tool_rate_limit_buckets", schema="tool")
    op.drop_table("tool_results", schema="tool")
    op.drop_index("ix_tool_calls_tool_started", table_name="tool_calls", schema="tool")
    op.drop_index("ix_tool_calls_run_task", table_name="tool_calls", schema="tool")
    op.drop_table("tool_calls", schema="tool")
    op.drop_index(
        "ix_tool_catalog_versions_active",
        table_name="tool_catalog_versions",
        schema="tool",
    )
    op.drop_table("tool_catalog_versions", schema="tool")
