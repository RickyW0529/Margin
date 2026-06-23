"""Add v0.2 text indexing link and audit tables.

Revision ID: 20260622_0026_text_indexing
Revises: 20260622_0025_news_refresh
Create Date: 2026-06-23 08:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0026_text_indexing"
down_revision = "20260622_0025_news_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.add_column(
        "chunks",
        sa.Column(
            "locator",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "trust_level",
            sa.String(length=48),
            nullable=False,
            server_default="trusted_official_content",
        ),
    )
    op.add_column(
        "chunks",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_chunks_active_available",
        "chunks",
        ["is_active", "available_at"],
    )

    op.create_table(
        "chunk_security_links",
        sa.Column("chunk_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), primary_key=True),
        sa.Column("link_type", sa.String(length=32), primary_key=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.chunk_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "security_id",
            "link_type",
            name="uq_chunk_security_link",
        ),
    )
    op.create_index(
        "ix_chunk_security_links_security",
        "chunk_security_links",
        ["security_id", "chunk_id"],
    )

    op.create_table(
        "indexed_documents",
        sa.Column("document_id", sa.String(length=64), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column(
            "chunk_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "embedding_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_indexed_documents_event_id", "indexed_documents", ["event_id"])


def downgrade() -> None:
    """downgrade."""
    op.drop_index("ix_indexed_documents_event_id", table_name="indexed_documents")
    op.drop_table("indexed_documents")
    op.drop_index(
        "ix_chunk_security_links_security",
        table_name="chunk_security_links",
    )
    op.drop_table("chunk_security_links")
    op.drop_index("ix_chunks_active_available", table_name="chunks")
    op.drop_column("chunks", "is_active")
    op.drop_column("chunks", "trust_level")
    op.drop_column("chunks", "locator")
