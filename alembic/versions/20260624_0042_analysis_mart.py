"""Add fourth-layer Analysis Mart tables.

Revision ID: 20260624_0042_analysis_mart
Revises: 20260624_0041_akshare_source
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260624_0042_analysis_mart"
down_revision = "20260624_0041_akshare_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create append-only Analysis Mart tables."""
    op.create_table(
        "analysis_snapshots",
        sa.Column("analysis_snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_kind", sa.String(length=64), nullable=False),
        sa.Column("quant_run_id", sa.String(length=64), nullable=True),
        sa.Column("quant_result_id", sa.String(length=64), nullable=True),
        sa.Column("input_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("strategy_version_id", sa.String(length=64), nullable=True),
        sa.Column("config_hash", sa.String(length=96), nullable=True),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("result_hash", sa.String(length=96), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_analysis_snapshots_security_scope_decision",
        "analysis_snapshots",
        ["security_id", "scope_version_id", "decision_at"],
    )
    op.create_index(
        "ix_analysis_snapshots_quant_run",
        "analysis_snapshots",
        ["quant_run_id", "security_id"],
    )

    op.create_table(
        "analysis_metrics",
        sa.Column("metric_id", sa.String(length=96), primary_key=True),
        sa.Column("analysis_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("metric_code", sa.String(length=128), nullable=False),
        sa.Column("metric_name", sa.String(length=256), nullable=False),
        sa.Column("metric_group", sa.String(length=64), nullable=False),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("percentile_market", sa.Float(), nullable=True),
        sa.Column("percentile_industry", sa.Float(), nullable=True),
        sa.Column("rank_market", sa.Integer(), nullable=True),
        sa.Column("rank_industry", sa.Integer(), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("detail_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_analysis_metrics_snapshot_group",
        "analysis_metrics",
        ["analysis_snapshot_id", "metric_group"],
    )
    op.create_index(
        "ix_analysis_metrics_analysis_snapshot_id",
        "analysis_metrics",
        ["analysis_snapshot_id"],
    )

    op.create_table(
        "analysis_findings",
        sa.Column("finding_id", sa.String(length=96), primary_key=True),
        sa.Column("analysis_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("detail_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_analysis_findings_snapshot_type",
        "analysis_findings",
        ["analysis_snapshot_id", "finding_type"],
    )
    op.create_index(
        "ix_analysis_findings_analysis_snapshot_id",
        "analysis_findings",
        ["analysis_snapshot_id"],
    )

    op.create_table(
        "analysis_evidence_links",
        sa.Column("link_id", sa.String(length=96), primary_key=True),
        sa.Column("analysis_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("finding_id", sa.String(length=96), nullable=True),
        sa.Column("metric_id", sa.String(length=96), nullable=True),
        sa.Column("evidence_id", sa.String(length=96), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("detail_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_analysis_evidence_links_snapshot",
        "analysis_evidence_links",
        ["analysis_snapshot_id"],
    )
    op.create_index(
        "ix_analysis_evidence_links_evidence",
        "analysis_evidence_links",
        ["evidence_id"],
    )


def downgrade() -> None:
    """Drop Analysis Mart tables."""
    op.drop_index("ix_analysis_evidence_links_evidence", table_name="analysis_evidence_links")
    op.drop_index("ix_analysis_evidence_links_snapshot", table_name="analysis_evidence_links")
    op.drop_table("analysis_evidence_links")
    op.drop_index("ix_analysis_findings_analysis_snapshot_id", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_snapshot_type", table_name="analysis_findings")
    op.drop_table("analysis_findings")
    op.drop_index("ix_analysis_metrics_analysis_snapshot_id", table_name="analysis_metrics")
    op.drop_index("ix_analysis_metrics_snapshot_group", table_name="analysis_metrics")
    op.drop_table("analysis_metrics")
    op.drop_index("ix_analysis_snapshots_quant_run", table_name="analysis_snapshots")
    op.drop_index(
        "ix_analysis_snapshots_security_scope_decision",
        table_name="analysis_snapshots",
    )
    op.drop_table("analysis_snapshots")
