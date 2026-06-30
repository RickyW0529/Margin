"""Add agentic news acquisition audit tables.

Revision ID: 20260629_0045_agentic_news
Revises: 20260625_0044_dead_schema
Create Date: 2026-06-29 00:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260629_0045_agentic_news"
down_revision = "20260625_0044_dead_schema"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create agentic news acquisition tables."""
    op.create_table(
        "news_agent_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("quant_run_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "include_near_threshold",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("config_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "error_summary",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_news_agent_runs_scope_decision",
        "news_agent_runs",
        ["scope_version_id", "decision_at"],
    )
    op.create_index(
        "ix_news_agent_runs_quant_run",
        "news_agent_runs",
        ["quant_run_id"],
    )
    op.create_index("ix_news_agent_runs_status", "news_agent_runs", ["status"])

    op.create_table(
        "news_agent_tasks",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32)),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("schema_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("request_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("response_hash", sa.String(length=96)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("payload", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_agent_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_news_agent_tasks_run_type",
        "news_agent_tasks",
        ["run_id", "task_type"],
    )
    op.create_index(
        "ix_news_agent_tasks_security",
        "news_agent_tasks",
        ["security_id", "run_id"],
    )

    op.create_table(
        "news_search_plans",
        sa.Column("plan_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("queries", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("prompt_version", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("response_hash", sa.String(length=96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_agent_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_news_search_plans_run_security",
        "news_search_plans",
        ["run_id", "security_id"],
    )

    op.create_table(
        "news_article_findings",
        sa.Column("finding_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("key_points", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("materiality", sa.String(length=32)),
        sa.Column("sentiment", sa.String(length=32)),
        sa.Column("risk_flags", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cited_spans", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("prompt_version", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("response_hash", sa.String(length=96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_agent_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_news_article_findings_run_security",
        "news_article_findings",
        ["run_id", "security_id"],
    )
    op.create_index(
        "ix_news_article_findings_event",
        "news_article_findings",
        ["event_id"],
    )

    op.create_table(
        "news_security_briefs",
        sa.Column("brief_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("finding_ids", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "source_event_ids",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_derived", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trust_level", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(length=96), nullable=False, server_default=""),
        sa.Column("response_hash", sa.String(length=96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_agent_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_news_security_briefs_run_security",
        "news_security_briefs",
        ["run_id", "security_id"],
    )


def downgrade() -> None:
    """Drop agentic news acquisition tables."""
    op.drop_index("ix_news_security_briefs_run_security", table_name="news_security_briefs")
    op.drop_table("news_security_briefs")
    op.drop_index("ix_news_article_findings_event", table_name="news_article_findings")
    op.drop_index(
        "ix_news_article_findings_run_security",
        table_name="news_article_findings",
    )
    op.drop_table("news_article_findings")
    op.drop_index("ix_news_search_plans_run_security", table_name="news_search_plans")
    op.drop_table("news_search_plans")
    op.drop_index("ix_news_agent_tasks_security", table_name="news_agent_tasks")
    op.drop_index("ix_news_agent_tasks_run_type", table_name="news_agent_tasks")
    op.drop_table("news_agent_tasks")
    op.drop_index("ix_news_agent_runs_status", table_name="news_agent_runs")
    op.drop_index("ix_news_agent_runs_quant_run", table_name="news_agent_runs")
    op.drop_index("ix_news_agent_runs_scope_decision", table_name="news_agent_runs")
    op.drop_table("news_agent_runs")
