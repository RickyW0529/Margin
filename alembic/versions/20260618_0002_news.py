"""Add news acquisition, search, and dedup persistence tables.

Revision ID: 20260618_0002_news
Revises: 20260618_0001
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260618_0002_news"
down_revision: str | None = "20260618_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create news persistence tables."""
    op.create_table(
        "source_cursors",
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("cursor_key", sa.String(length=128), nullable=False),
        sa.Column("cursor_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_name", "cursor_key"),
    )
    op.create_table(
        "raw_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=96), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("raw_size", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        op.f("ix_raw_snapshots_content_hash"),
        "raw_snapshots",
        ["content_hash"],
        unique=False,
    )
    op.create_table(
        "document_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_level", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=96), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=96), nullable=True),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("is_original", sa.Boolean(), nullable=False),
        sa.Column("duplicate_of", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["raw_snapshots.snapshot_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        op.f("ix_document_events_content_hash"),
        "document_events",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_events_document_id"),
        "document_events",
        ["document_id"],
        unique=False,
    )
    op.create_index("ix_document_events_source_url", "document_events", ["source_url"])
    op.create_index(
        "ix_document_events_symbol_time",
        "document_events",
        ["symbols", "published_at"],
    )
    op.create_table(
        "document_outbox",
        sa.Column("outbox_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["document_events.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("outbox_id"),
        sa.UniqueConstraint("event_id", "topic", name="uq_document_outbox_event_topic"),
    )
    op.create_index(
        "ix_document_outbox_status_topic",
        "document_outbox",
        ["topic", "status", "created_at"],
    )
    op.create_table(
        "search_queries",
        sa.Column("query_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("api_provider", sa.String(length=64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_table(
        "search_results",
        sa.Column("result_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=False),
        sa.Column("result_index", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("source_level", sa.Integer(), nullable=False),
        sa.Column("has_accessible_original", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=96), nullable=True),
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["query_id"], ["search_queries.query_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("query_id", "result_index", name="uq_search_result_index"),
    )
    op.create_index("ix_search_results_url", "search_results", ["url"], unique=False)
    op.create_table(
        "dedup_records",
        sa.Column("duplicate_event_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_event_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["document_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("duplicate_event_id"),
    )
    op.create_index(
        op.f("ix_dedup_records_canonical_event_id"),
        "dedup_records",
        ["canonical_event_id"],
    )
    op.create_table(
        "repost_edges",
        sa.Column("parent_event_id", sa.String(length=64), nullable=False),
        sa.Column("child_event_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["child_event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_event_id"],
            ["document_events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("parent_event_id", "child_event_id"),
    )


def downgrade() -> None:
    """Drop news persistence tables."""
    op.drop_table("repost_edges")
    op.drop_index(op.f("ix_dedup_records_canonical_event_id"), table_name="dedup_records")
    op.drop_table("dedup_records")
    op.drop_index("ix_search_results_url", table_name="search_results")
    op.drop_table("search_results")
    op.drop_table("search_queries")
    op.drop_index("ix_document_outbox_status_topic", table_name="document_outbox")
    op.drop_table("document_outbox")
    op.drop_index("ix_document_events_symbol_time", table_name="document_events")
    op.drop_index("ix_document_events_source_url", table_name="document_events")
    op.drop_index(op.f("ix_document_events_document_id"), table_name="document_events")
    op.drop_index(op.f("ix_document_events_content_hash"), table_name="document_events")
    op.drop_table("document_events")
    op.drop_index(op.f("ix_raw_snapshots_content_hash"), table_name="raw_snapshots")
    op.drop_table("raw_snapshots")
    op.drop_table("source_cursors")
