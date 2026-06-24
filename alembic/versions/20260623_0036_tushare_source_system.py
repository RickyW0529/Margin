"""Add the independent Tushare source system and quality boundary.

Revision ID: 20260623_0036_tushare_source
Revises: 20260623_0035_data_policy
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260623_0036_tushare_source"
down_revision = "20260623_0035_data_policy"
branch_labels = None
depends_on = None

TUSHARE_ENDPOINTS = (
    "stock_basic",
    "namechange",
    "trade_cal",
    "daily",
    "adj_factor",
    "suspend_d",
    "daily_basic",
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "fina_audit",
    "index_classify",
    "index_member",
    "pledge_stat",
    "index_daily",
    "index_weight",
)


def upgrade() -> None:
    """Create endpoint-specific landing tables and quality decisions."""
    op.execute("CREATE SCHEMA IF NOT EXISTS source_tushare")
    op.create_table(
        "quant_data_requirements",
        sa.Column("requirement_code", sa.String(length=96), nullable=False),
        sa.Column("consumer", sa.String(length=160), nullable=False),
        sa.Column("warehouse_fields", postgresql.JSONB(), nullable=False),
        sa.Column("minimum_history_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("requirement_code", "catalog_version"),
        sa.CheckConstraint(
            "minimum_history_days >= 0",
            name="ck_quant_requirement_history",
        ),
    )
    op.create_table(
        "provider_endpoint_requirements",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("api_name", sa.String(length=96), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("admission", sa.String(length=32), nullable=False),
        sa.Column("partition_by", sa.String(length=64), nullable=False),
        sa.Column("natural_key_fields", postgresql.JSONB(), nullable=False),
        sa.Column("pit_fields", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider", "api_name", "catalog_version"),
        sa.CheckConstraint(
            "admission IN ('enabled', 'out_of_scope')",
            name="ck_provider_endpoint_admission",
        ),
    )
    op.create_index(
        "ix_provider_endpoint_requirements_admission",
        "provider_endpoint_requirements",
        ["provider", "admission", "domain"],
    )
    op.create_table(
        "provider_endpoint_requirement_links",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("api_name", sa.String(length=96), nullable=False),
        sa.Column("requirement_code", sa.String(length=96), nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider", "api_name", "catalog_version"],
            [
                "provider_endpoint_requirements.provider",
                "provider_endpoint_requirements.api_name",
                "provider_endpoint_requirements.catalog_version",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_code", "catalog_version"],
            [
                "quant_data_requirements.requirement_code",
                "quant_data_requirements.catalog_version",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "provider",
            "api_name",
            "requirement_code",
            "catalog_version",
        ),
    )

    for endpoint in TUSHARE_ENDPOINTS:
        table_name = f"ts_{endpoint}"
        op.create_table(
            table_name,
            sa.Column("source_row_id", sa.String(length=72), primary_key=True),
            sa.Column("natural_key_hash", sa.String(length=80), nullable=False),
            sa.Column("revision_hash", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=True),
            sa.Column("business_date", sa.Date(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_partition", sa.String(length=16), nullable=False),
            sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
            sa.Column("raw_snapshot_id", sa.String(length=64), nullable=True),
            sa.Column("sync_run_id", sa.String(length=64), nullable=False),
            sa.Column(
                "quality_status",
                sa.String(length=24),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["raw_snapshot_id"],
                ["public.raw_data_snapshots.snapshot_id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["sync_run_id"],
                ["public.data_sync_runs.run_id"],
                ondelete="RESTRICT",
            ),
            sa.UniqueConstraint(
                "natural_key_hash",
                "revision_hash",
                name=f"uq_{table_name}_natural_revision",
            ),
            sa.CheckConstraint(
                "quality_status IN ('pending', 'accepted', 'quarantined', 'rejected')",
                name=f"ck_{table_name}_quality_status",
            ),
            schema="source_tushare",
        )
        op.create_index(
            f"ix_{table_name}_symbol_business",
            table_name,
            ["symbol", "business_date"],
            schema="source_tushare",
        )
        op.create_index(
            f"ix_{table_name}_business_date",
            table_name,
            ["business_date"],
            schema="source_tushare",
        )
        op.create_index(
            f"ix_{table_name}_pending_quality",
            table_name,
            ["fetched_at", "source_row_id"],
            schema="source_tushare",
            postgresql_where=sa.text("quality_status = 'pending'"),
        )

    op.create_table(
        "source_quality_decisions",
        sa.Column("decision_id", sa.String(length=72), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=96), nullable=False),
        sa.Column("source_row_id", sa.String(length=72), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("issue_codes", postgresql.JSONB(), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("published_fact_count", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "endpoint",
            "source_row_id",
            "rule_version",
            name="uq_source_quality_decision",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'quarantined', 'rejected')",
            name="ck_source_quality_decision",
        ),
        sa.CheckConstraint(
            "quality_score BETWEEN 0 AND 1",
            name="ck_source_quality_score",
        ),
        sa.CheckConstraint(
            "published_fact_count >= 0",
            name="ck_source_quality_published_count",
        ),
    )
    op.create_index(
        "ix_source_quality_endpoint_decision",
        "source_quality_decisions",
        ["provider", "endpoint", "decision", "checked_at"],
    )
    op.create_index(
        "ix_source_quality_rejected",
        "source_quality_decisions",
        ["endpoint", "checked_at"],
        postgresql_where=sa.text("decision <> 'accepted'"),
    )


def downgrade() -> None:
    """Drop quality metadata and the independent Tushare source schema."""
    op.drop_index(
        "ix_source_quality_rejected",
        table_name="source_quality_decisions",
    )
    op.drop_index(
        "ix_source_quality_endpoint_decision",
        table_name="source_quality_decisions",
    )
    op.drop_table("source_quality_decisions")
    op.execute("DROP SCHEMA IF EXISTS source_tushare CASCADE")
    op.drop_table("provider_endpoint_requirement_links")
    op.drop_index(
        "ix_provider_endpoint_requirements_admission",
        table_name="provider_endpoint_requirements",
    )
    op.drop_table("provider_endpoint_requirements")
    op.drop_table("quant_data_requirements")
