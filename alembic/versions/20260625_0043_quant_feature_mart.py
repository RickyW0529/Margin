"""Add fourth-layer Quant Feature Mart.

Revision ID: 20260625_0043_quant_feature_mart
Revises: 20260624_0042_analysis_mart
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260625_0043_quant_feature_mart"
down_revision = "20260624_0042_analysis_mart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create fourth-layer quant feature tables and input binding."""
    op.add_column(
        "quant_input_snapshots",
        sa.Column("feature_snapshot_id", sa.String(length=64), nullable=True),
    )

    op.create_table(
        "quant_feature_snapshots",
        sa.Column("feature_snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("universe_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("feature_set_version_id", sa.String(length=64), nullable=True),
        sa.Column("feature_schema_version", sa.String(length=64), nullable=False),
        sa.Column("source_layer", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("feature_columns", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("lineage_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quant_feature_snapshots_scope_decision",
        "quant_feature_snapshots",
        ["scope_version_id", "decision_at"],
    )
    op.create_index(
        "ix_quant_feature_snapshots_universe",
        "quant_feature_snapshots",
        ["universe_snapshot_id", "decision_at"],
    )

    op.create_table(
        "quant_feature_rows",
        sa.Column("row_id", sa.String(length=96), primary_key=True),
        sa.Column("feature_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("industry_id", sa.String(length=128), nullable=True),
        sa.Column("features_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quant_feature_rows_snapshot_security",
        "quant_feature_rows",
        ["feature_snapshot_id", "security_id"],
    )
    op.create_index(
        "ix_quant_feature_rows_feature_snapshot_id",
        "quant_feature_rows",
        ["feature_snapshot_id"],
    )


def downgrade() -> None:
    """Drop fourth-layer quant feature tables and input binding."""
    op.drop_index(
        "ix_quant_feature_rows_feature_snapshot_id",
        table_name="quant_feature_rows",
    )
    op.drop_index(
        "ix_quant_feature_rows_snapshot_security",
        table_name="quant_feature_rows",
    )
    op.drop_table("quant_feature_rows")
    op.drop_index(
        "ix_quant_feature_snapshots_universe",
        table_name="quant_feature_snapshots",
    )
    op.drop_index(
        "ix_quant_feature_snapshots_scope_decision",
        table_name="quant_feature_snapshots",
    )
    op.drop_table("quant_feature_snapshots")
    op.drop_column("quant_input_snapshots", "feature_snapshot_id")
