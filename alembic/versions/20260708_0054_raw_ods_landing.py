"""Add v1 raw metadata and ODS landing tables.

Revision ID: 20260708_0054_raw_ods_landing
Revises: 20260708_0053_v1_warehouse_schemas
Create Date: 2026-07-08 23:55:00
"""

from __future__ import annotations

# ruff: noqa: E501
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0054_raw_ods"
down_revision = "20260708_0053_v1_schemas"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Process _jsonb.

    Returns:
        postgresql.JSONB: Return value.
    """
    return postgresql.JSONB(astext_type=sa.Text())


def _text_array() -> postgresql.ARRAY:
    """Process _text_array.

    Returns:
        postgresql.ARRAY: Return value.
    """
    return postgresql.ARRAY(sa.Text())


def upgrade() -> None:
    """Create raw_meta and representative source landing tables."""
    op.create_table(
        "raw_data_snapshots",
        sa.Column("raw_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("request_params_json", _jsonb(), nullable=False),
        sa.Column("request_params_hash", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_published_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_storage_uri", sa.Text()),
        sa.Column("raw_payload_hash", sa.Text()),
        sa.Column("schema_hash", sa.Text()),
        sa.Column("sync_run_id", sa.Text()),
        sa.Column("quality_status", sa.Text(), nullable=False, server_default="unchecked"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="raw_meta",
    )
    op.create_index(
        "ix_raw_snapshots_provider_endpoint",
        "raw_data_snapshots",
        ["provider_name", "endpoint_name"],
        schema="raw_meta",
    )
    op.create_index(
        "ix_raw_snapshots_available_at",
        "raw_data_snapshots",
        ["available_at"],
        schema="raw_meta",
    )
    op.create_table(
        "raw_document_snapshots",
        sa.Column("document_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_storage_uri", sa.Text()),
        sa.Column("raw_payload_hash", sa.Text()),
        sa.Column("parse_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="raw_meta",
    )
    _create_quote_landing("source_tushare", "ods_daily_quote_raw")
    _create_quote_landing("source_akshare", "ods_daily_quote_raw")
    op.create_table(
        "raw_filings",
        sa.Column("landing_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_snapshot_id", sa.Text(), sa.ForeignKey("raw_meta.raw_document_snapshots.document_snapshot_id"), nullable=False),
        sa.Column("security_code", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_json", _jsonb(), nullable=False),
        sa.Column("natural_key_hash", sa.Text(), nullable=False),
        sa.Column("revision_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("natural_key_hash", "revision_hash", name="uq_raw_filings_revision"),
        schema="source_filing",
    )
    op.create_table(
        "raw_articles",
        sa.Column("landing_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_snapshot_id", sa.Text(), sa.ForeignKey("raw_meta.raw_document_snapshots.document_snapshot_id"), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_json", _jsonb(), nullable=False),
        sa.Column("natural_key_hash", sa.Text(), nullable=False),
        sa.Column("revision_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("natural_key_hash", "revision_hash", name="uq_raw_articles_revision"),
        schema="source_news",
    )
    op.create_table(
        "raw_documents",
        sa.Column("landing_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_snapshot_id", sa.Text(), sa.ForeignKey("raw_meta.raw_document_snapshots.document_snapshot_id"), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("source_locator", sa.Text()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_json", _jsonb(), nullable=False),
        sa.Column("natural_key_hash", sa.Text(), nullable=False),
        sa.Column("revision_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("natural_key_hash", "revision_hash", name="uq_raw_documents_revision"),
        schema="source_doc",
    )


def _create_quote_landing(schema: str, table_name: str) -> None:
    """Process _create_quote_landing.

    Args:
        schema (str): Parameter description.
        table_name (str): Parameter description.

    Returns:
        None: Return value.
    """
    op.create_table(
        table_name,
        sa.Column("landing_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_snapshot_id", sa.Text(), sa.ForeignKey("raw_meta.raw_data_snapshots.raw_snapshot_id"), nullable=False),
        sa.Column("sync_run_id", sa.Text()),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("provider_row_key", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric()),
        sa.Column("high", sa.Numeric()),
        sa.Column("low", sa.Numeric()),
        sa.Column("close", sa.Numeric()),
        sa.Column("pre_close", sa.Numeric()),
        sa.Column("change", sa.Numeric()),
        sa.Column("pct_chg", sa.Numeric()),
        sa.Column("vol", sa.Numeric()),
        sa.Column("amount", sa.Numeric()),
        sa.Column("raw_payload_json", _jsonb(), nullable=False),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("natural_key_hash", sa.Text(), nullable=False),
        sa.Column("revision_hash", sa.Text(), nullable=False),
        sa.Column("provider_published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_status", sa.Text(), nullable=False, server_default="loaded"),
        sa.Column("quality_flags", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("natural_key_hash", "revision_hash", name=f"uq_{schema}_{table_name}_revision"),
        schema=schema,
    )
    op.create_index(
        f"ix_{schema}_{table_name}_code_date",
        table_name,
        ["ts_code", "trade_date"],
        schema=schema,
    )
    op.create_index(
        f"ix_{schema}_{table_name}_available",
        table_name,
        ["available_at"],
        schema=schema,
    )


def downgrade() -> None:
    """Drop only tables introduced by this revision."""
    for schema, table in (
        ("source_doc", "raw_documents"),
        ("source_news", "raw_articles"),
        ("source_filing", "raw_filings"),
        ("source_akshare", "ods_daily_quote_raw"),
        ("source_tushare", "ods_daily_quote_raw"),
        ("raw_meta", "raw_document_snapshots"),
        ("raw_meta", "raw_data_snapshots"),
    ):
        op.drop_table(table, schema=schema)
