"""Add formal v1 Context Engineering tables.

Revision ID: 20260709_0060_context
Revises: 20260709_0059_warehouse_layers
Create Date: 2026-07-09 16:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260709_0060_context"
down_revision = "20260709_0059_warehouse_layers"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return PostgreSQL JSONB with text astype."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create the formal Context Engineering persistence schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")
    op.create_table(
        "context_packs",
        sa.Column("context_pack_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("created_for_agent", sa.Text(), nullable=False),
        sa.Column("user_goal", sa.Text(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("policy_snapshot_ref", sa.Text()),
        sa.Column("pack_json", _jsonb(), nullable=False),
        sa.Column("pack_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("token_budget > 0", name="ck_context_packs_token_budget_positive"),
        schema="agent",
    )
    op.create_index("ix_context_packs_run_id", "context_packs", ["run_id"], schema="agent")
    op.create_index(
        "ix_context_packs_agent",
        "context_packs",
        ["created_for_agent"],
        schema="agent",
    )

    op.create_table(
        "context_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column(
            "context_pack_id",
            sa.Text(),
            sa.ForeignKey("agent.context_packs.context_pack_id"),
            nullable=False,
        ),
        sa.Column("fact_type", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("value_json", _jsonb()),
        sa.Column("as_of_date", sa.Date()),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column(
            "source_artifact_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_locators",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("freshness_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column(
            "pii_or_secret_risk",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("valid_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_context_facts_confidence_range",
        ),
        schema="agent",
    )
    op.create_index("ix_context_facts_pack", "context_facts", ["context_pack_id"], schema="agent")
    op.create_index(
        "ix_context_facts_subject",
        "context_facts",
        ["subject_type", "subject_id"],
        schema="agent",
    )
    op.create_index("ix_context_facts_type", "context_facts", ["fact_type"], schema="agent")
    op.create_index(
        "ix_context_facts_available_at",
        "context_facts",
        ["available_at"],
        schema="agent",
    )

    op.create_table(
        "context_omissions",
        sa.Column("omission_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "context_pack_id",
            sa.Text(),
            sa.ForeignKey("agent.context_packs.context_pack_id"),
            nullable=False,
        ),
        sa.Column("omitted_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="agent",
    )
    op.create_index(
        "ix_context_omissions_pack",
        "context_omissions",
        ["context_pack_id"],
        schema="agent",
    )

    op.create_table(
        "domain_context_capsules",
        sa.Column("capsule_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("domain_task_id", sa.Text(), nullable=False),
        sa.Column("expert_agent", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("capsule_json", _jsonb(), nullable=False),
        sa.Column("capsule_hash", sa.Text(), nullable=False),
        sa.Column(
            "output_artifact_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("audit_report_ref", sa.Text()),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="agent",
    )
    op.create_index(
        "ix_domain_capsules_run",
        "domain_context_capsules",
        ["run_id"],
        schema="agent",
    )
    op.create_index(
        "ix_domain_capsules_domain",
        "domain_context_capsules",
        ["domain"],
        schema="agent",
    )

    op.create_table(
        "artifact_lineage_edges",
        sa.Column("edge_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("from_ref", sa.Text(), nullable=False),
        sa.Column("to_ref", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("from_ref", "to_ref", "edge_type", name="uq_artifact_lineage_edge"),
        schema="agent",
    )
    op.create_index(
        "ix_artifact_lineage_run",
        "artifact_lineage_edges",
        ["run_id"],
        schema="agent",
    )
    op.create_index(
        "ix_artifact_lineage_to",
        "artifact_lineage_edges",
        ["to_ref"],
        schema="agent",
    )


def downgrade() -> None:
    """Drop the formal Context Engineering persistence schema."""
    op.drop_index("ix_artifact_lineage_to", table_name="artifact_lineage_edges", schema="agent")
    op.drop_index("ix_artifact_lineage_run", table_name="artifact_lineage_edges", schema="agent")
    op.drop_table("artifact_lineage_edges", schema="agent")
    op.drop_index("ix_domain_capsules_domain", table_name="domain_context_capsules", schema="agent")
    op.drop_index("ix_domain_capsules_run", table_name="domain_context_capsules", schema="agent")
    op.drop_table("domain_context_capsules", schema="agent")
    op.drop_index("ix_context_omissions_pack", table_name="context_omissions", schema="agent")
    op.drop_table("context_omissions", schema="agent")
    op.drop_index("ix_context_facts_available_at", table_name="context_facts", schema="agent")
    op.drop_index("ix_context_facts_type", table_name="context_facts", schema="agent")
    op.drop_index("ix_context_facts_subject", table_name="context_facts", schema="agent")
    op.drop_index("ix_context_facts_pack", table_name="context_facts", schema="agent")
    op.drop_table("context_facts", schema="agent")
    op.drop_index("ix_context_packs_agent", table_name="context_packs", schema="agent")
    op.drop_index("ix_context_packs_run_id", table_name="context_packs", schema="agent")
    op.drop_table("context_packs", schema="agent")
