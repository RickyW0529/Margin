"""Add vector chunk, embedding, and retrieval audit tables.

Revision ID: 20260618_0003_vector
Revises: 20260618_0002_news
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260618_0003_vector"
down_revision: str | None = "20260618_0002_news"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create vector persistence tables."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=96), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("source_level", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=96), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_id", sa.String(length=64), nullable=True),
        sa.Column("row_id", sa.String(length=64), nullable=True),
        sa.Column("quote_span", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(op.f("ix_chunks_content_hash"), "chunks", ["content_hash"])
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"])
    op.create_index("ix_chunks_doc_type", "chunks", ["doc_type"])
    op.create_index("ix_chunks_symbol_available", "chunks", ["symbol", "available_at"])
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.chunk_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id", "provider_name", "model_name", "model_version"),
    )
    op.create_table(
        "index_audit_records",
        sa.Column("audit_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("vector_count", sa.Integer(), nullable=False),
        sa.Column("keyword_count", sa.Integer(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_table(
        "retrieval_audit_records",
        sa.Column("audit_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )


def downgrade() -> None:
    """Drop vector persistence tables."""
    op.drop_table("retrieval_audit_records")
    op.drop_table("index_audit_records")
    op.drop_table("chunk_embeddings")
    op.drop_index("ix_chunks_symbol_available", table_name="chunks")
    op.drop_index("ix_chunks_doc_type", table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_content_hash"), table_name="chunks")
    op.drop_table("chunks")
