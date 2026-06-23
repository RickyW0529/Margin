"""Add v0.2 news refresh target queue tables.

Revision ID: 20260622_0025_news_refresh
Revises: 20260622_0024_assessment_pointer
Create Date: 2026-06-23 07:18:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0025_news_refresh"
down_revision = "20260622_0024_assessment_pointer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.create_table(
        "news_refresh_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("quant_run_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_final_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "error_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_news_refresh_runs_scope_version_id",
        "news_refresh_runs",
        ["scope_version_id"],
    )
    op.create_index(
        "ix_news_refresh_runs_quant_run_id",
        "news_refresh_runs",
        ["quant_run_id"],
    )
    op.create_index("ix_news_refresh_runs_status", "news_refresh_runs", ["status"])

    op.create_table(
        "news_refresh_targets",
        sa.Column("target_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=96), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.String(length=48), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_refresh_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "dedupe_key", name="uq_news_target_dedupe"),
    )
    op.create_index(
        "ix_news_refresh_targets_security_id",
        "news_refresh_targets",
        ["security_id"],
    )
    op.create_index(
        "ix_news_target_claim",
        "news_refresh_targets",
        ["run_id", "status", "priority", "next_attempt_at"],
    )
    op.create_index(
        "ix_news_target_security_run",
        "news_refresh_targets",
        ["security_id", "run_id"],
    )

    op.create_table(
        "document_security_links",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_document_security_links_security",
        "document_security_links",
        ["security_id", "event_id"],
    )

    op.create_table(
        "document_materiality_scores",
        sa.Column("score_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("materiality_score", sa.Float(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("risk_polarity", sa.String(length=32), nullable=False),
        sa.Column("is_material", sa.Boolean(), nullable=False),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("scoring_version", sa.String(length=64), nullable=False),
        sa.Column("is_untrusted_external_text", sa.Boolean(), nullable=False),
        sa.Column("can_directly_change_research_state", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "event_id",
            "security_id",
            "scoring_version",
            name="uq_document_materiality_version",
        ),
    )
    op.create_index(
        "ix_document_materiality_security",
        "document_materiality_scores",
        ["security_id", "is_material", "materiality_score"],
    )

    op.create_table(
        "news_context_bundles",
        sa.Column("bundle_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("target_completion_state", sa.String(length=32), nullable=False),
        sa.Column("can_support_verified_carry_forward", sa.Boolean(), nullable=False),
        sa.Column(
            "incomplete_reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["news_refresh_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_news_context_bundles_run_id",
        "news_context_bundles",
        ["run_id"],
    )
    op.create_index(
        "ix_news_context_bundles_security_id",
        "news_context_bundles",
        ["security_id"],
    )

    op.create_table(
        "news_context_documents",
        sa.Column("bundle_id", sa.String(length=64), primary_key=True),
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["news_context_bundles.bundle_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("bundle_id", "event_id", name="uq_news_context_document"),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_table("news_context_documents")
    op.drop_index("ix_news_context_bundles_security_id", table_name="news_context_bundles")
    op.drop_index("ix_news_context_bundles_run_id", table_name="news_context_bundles")
    op.drop_table("news_context_bundles")
    op.drop_index(
        "ix_document_materiality_security",
        table_name="document_materiality_scores",
    )
    op.drop_table("document_materiality_scores")
    op.drop_index(
        "ix_document_security_links_security",
        table_name="document_security_links",
    )
    op.drop_table("document_security_links")
    op.drop_index("ix_news_target_security_run", table_name="news_refresh_targets")
    op.drop_index("ix_news_target_claim", table_name="news_refresh_targets")
    op.drop_index(
        "ix_news_refresh_targets_security_id",
        table_name="news_refresh_targets",
    )
    op.drop_table("news_refresh_targets")
    op.drop_index("ix_news_refresh_runs_status", table_name="news_refresh_runs")
    op.drop_index("ix_news_refresh_runs_quant_run_id", table_name="news_refresh_runs")
    op.drop_index("ix_news_refresh_runs_scope_version_id", table_name="news_refresh_runs")
    op.drop_table("news_refresh_runs")
