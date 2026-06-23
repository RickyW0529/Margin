"""Add v0.2 RAG evidence package and conflict tables.

Revision ID: 20260622_0027_rag_evidence
Revises: 20260622_0026_text_indexing
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0027_rag_evidence"
down_revision = "20260622_0026_text_indexing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the v0.2 RAG evidence schema."""
    op.create_table(
        "evidence_packages",
        sa.Column("package_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(length=128), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("claim_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflict_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("max_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieval_audit_id", sa.String(length=64), nullable=True),
        sa.Column("parent_package_id", sa.String(length=64), nullable=True),
        sa.Column(
            "added_evidence_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("package_id", "version"),
    )
    op.create_index(
        "ix_evidence_packages_security_decision",
        "evidence_packages",
        ["security_id", "decision_at"],
    )
    op.create_index(
        "ix_evidence_packages_parent",
        "evidence_packages",
        ["parent_package_id"],
    )

    op.create_table(
        "evidence_package_items",
        sa.Column("package_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id", "version"],
            ["evidence_packages.package_id", "evidence_packages.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("package_id", "version", "item_type", "item_id"),
    )
    op.create_index(
        "ix_evidence_package_items_item",
        "evidence_package_items",
        ["item_type", "item_id"],
    )

    op.create_table(
        "claim_evidence_links",
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["evidence_claims.claim_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id", "role"),
        sa.UniqueConstraint(
            "claim_id",
            "evidence_id",
            "role",
            name="uq_claim_evidence_link_role",
        ),
    )
    op.create_index(
        "ix_claim_evidence_links_evidence",
        "claim_evidence_links",
        ["evidence_id"],
    )

    op.create_table(
        "evidence_conflicts",
        sa.Column("conflict_id", sa.String(length=64), nullable=False),
        sa.Column("package_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("conflicting_evidence_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id", "version"],
            ["evidence_packages.package_id", "evidence_packages.version"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conflicting_evidence_id"],
            ["evidence_records.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index(
        "ix_evidence_conflicts_package",
        "evidence_conflicts",
        ["package_id", "version"],
    )
    op.create_index(
        "ix_evidence_conflicts_security",
        "evidence_conflicts",
        ["security_id"],
    )

    op.create_table(
        "news_context_evidence",
        sa.Column("bundle_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["news_context_bundles.bundle_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("bundle_id", "evidence_id"),
        sa.UniqueConstraint(
            "bundle_id",
            "evidence_id",
            name="uq_news_context_evidence",
        ),
    )
    op.create_index(
        "ix_news_context_evidence_evidence",
        "news_context_evidence",
        ["evidence_id"],
    )


def downgrade() -> None:
    """Revert the v0.2 RAG evidence schema."""
    op.drop_index("ix_news_context_evidence_evidence", table_name="news_context_evidence")
    op.drop_table("news_context_evidence")
    op.drop_index("ix_evidence_conflicts_security", table_name="evidence_conflicts")
    op.drop_index("ix_evidence_conflicts_package", table_name="evidence_conflicts")
    op.drop_table("evidence_conflicts")
    op.drop_index("ix_claim_evidence_links_evidence", table_name="claim_evidence_links")
    op.drop_table("claim_evidence_links")
    op.drop_index("ix_evidence_package_items_item", table_name="evidence_package_items")
    op.drop_table("evidence_package_items")
    op.drop_index("ix_evidence_packages_parent", table_name="evidence_packages")
    op.drop_index(
        "ix_evidence_packages_security_decision",
        table_name="evidence_packages",
    )
    op.drop_table("evidence_packages")
