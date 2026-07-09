"""Add formal Agent prompt system tables.

Revision ID: 20260709_0062_prompts
Revises: 20260709_0061_tool_audit
Create Date: 2026-07-09 17:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260709_0062_prompts"
down_revision = "20260709_0061_tool_audit"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return PostgreSQL JSONB with text astype."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create formal PromptBundle and prompt audit tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS prompt")
    op.create_table(
        "prompt_templates",
        sa.Column("prompt_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column(
            "allowed_variables",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("output_schema_ref", sa.Text()),
        sa.Column("safety_tags", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="prompt",
    )
    op.create_index(
        "ix_prompt_templates_prompt",
        "prompt_templates",
        ["prompt_id"],
        schema="prompt",
    )

    op.create_table(
        "prompt_bundles",
        sa.Column("prompt_bundle_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("target_agent_type", sa.Text(), nullable=False),
        sa.Column("template_refs", _jsonb(), nullable=False),
        sa.Column("model_profile_ref", sa.Text(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="prompt",
    )
    op.create_index(
        "ix_prompt_bundles_target_active",
        "prompt_bundles",
        ["target_agent_type", "is_active"],
        schema="prompt",
    )

    op.create_table(
        "prompt_render_history",
        sa.Column("render_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("prompt_bundle_id", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("variables_hash", sa.Text(), nullable=False),
        sa.Column(
            "rendered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="prompt",
    )
    op.create_index(
        "ix_prompt_render_history_run",
        "prompt_render_history",
        ["run_id"],
        schema="prompt",
    )
    op.create_index(
        "ix_prompt_render_history_bundle",
        "prompt_render_history",
        ["prompt_bundle_id"],
        schema="prompt",
    )

    op.create_table(
        "llm_call_audits",
        sa.Column("llm_call_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_render_id", sa.Text(), nullable=False),
        sa.Column("input_token_count", sa.Integer()),
        sa.Column("output_token_count", sa.Integer()),
        sa.Column("temperature", sa.Numeric(4, 3)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        schema="prompt",
    )
    op.create_index("ix_llm_call_audits_run", "llm_call_audits", ["run_id"], schema="prompt")
    op.create_index(
        "ix_llm_call_audits_prompt_render",
        "llm_call_audits",
        ["prompt_render_id"],
        schema="prompt",
    )


def downgrade() -> None:
    """Drop formal PromptBundle and prompt audit tables."""
    op.drop_index(
        "ix_llm_call_audits_prompt_render",
        table_name="llm_call_audits",
        schema="prompt",
    )
    op.drop_index("ix_llm_call_audits_run", table_name="llm_call_audits", schema="prompt")
    op.drop_table("llm_call_audits", schema="prompt")
    op.drop_index(
        "ix_prompt_render_history_bundle",
        table_name="prompt_render_history",
        schema="prompt",
    )
    op.drop_index(
        "ix_prompt_render_history_run",
        table_name="prompt_render_history",
        schema="prompt",
    )
    op.drop_table("prompt_render_history", schema="prompt")
    op.drop_index(
        "ix_prompt_bundles_target_active",
        table_name="prompt_bundles",
        schema="prompt",
    )
    op.drop_table("prompt_bundles", schema="prompt")
    op.drop_index("ix_prompt_templates_prompt", table_name="prompt_templates", schema="prompt")
    op.drop_table("prompt_templates", schema="prompt")
