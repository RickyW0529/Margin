"""Add RAG evidence, claim, audit, and research evidence tables.

Revision ID: 20260618_0004_evidence
Revises: 20260618_0003_vector
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260618_0004_evidence"
down_revision: str | None = "20260618_0003_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create module 05 evidence persistence tables."""
    op.create_table(
        "evidence_records",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("source_level", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("content_hash", sa.String(length=96), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_id", sa.String(length=64), nullable=True),
        sa.Column("row_id", sa.String(length=64), nullable=True),
        sa.Column("quote_span", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index(op.f("ix_evidence_records_chunk_id"), "evidence_records", ["chunk_id"])
    op.create_index(
        "ix_evidence_records_content_hash",
        "evidence_records",
        ["content_hash"],
    )
    op.create_index("ix_evidence_records_document", "evidence_records", ["document_id"])
    op.create_index(
        "ix_evidence_records_symbol_available",
        "evidence_records",
        ["symbol", "available_at"],
    )
    op.create_table(
        "evidence_claims",
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("claim_type", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("fact_or_inference", sa.String(length=32), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("claim_id"),
    )
    op.create_index(
        "ix_evidence_claims_symbol_effective",
        "evidence_claims",
        ["symbol", "effective_at"],
    )
    op.create_table(
        "evidence_validation_audits",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("fail_reason", sa.String(length=64), nullable=True),
        sa.Column("original_confidence", sa.Float(), nullable=False),
        sa.Column("capped_confidence", sa.Float(), nullable=False),
        sa.Column("conflicts_found", sa.Integer(), nullable=False),
        sa.Column("evidences_checked", sa.Integer(), nullable=False),
        sa.Column("evidences_passed", sa.Integer(), nullable=False),
        sa.Column("requires_counter_review", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["evidence_claims.claim_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_evidence_validation_audits_claim",
        "evidence_validation_audits",
        ["claim_id", "checked_at"],
    )
    op.create_table(
        "research_evidence",
        sa.Column("research_item_id", sa.String(length=64), nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["evidence_claims.claim_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.evidence_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("research_item_id", "claim_id", "evidence_id", "role"),
    )


def downgrade() -> None:
    """Drop module 05 evidence persistence tables."""
    op.drop_table("research_evidence")
    op.drop_index("ix_evidence_validation_audits_claim", table_name="evidence_validation_audits")
    op.drop_table("evidence_validation_audits")
    op.drop_index("ix_evidence_claims_symbol_effective", table_name="evidence_claims")
    op.drop_table("evidence_claims")
    op.drop_index("ix_evidence_records_symbol_available", table_name="evidence_records")
    op.drop_index("ix_evidence_records_document", table_name="evidence_records")
    op.drop_index("ix_evidence_records_content_hash", table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_chunk_id"), table_name="evidence_records")
    op.drop_table("evidence_records")
