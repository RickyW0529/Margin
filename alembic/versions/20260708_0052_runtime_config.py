"""Add domain-specific runtime configuration zipper tables.

Revision ID: 20260708_0052_runtime_config
Revises: 20260708_0051_agent_chat
Create Date: 2026-07-08 20:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0052_runtime_config"
down_revision = "20260708_0051_agent_chat"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create runtime config domain tables and resolution snapshots."""
    op.create_table(
        "agent_flow_versions",
        sa.Column("version_id", sa.String(length=96), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("flow_id", sa.String(length=96), nullable=False),
        sa.Column("flow_version", sa.String(length=64), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("permission_mode", sa.String(length=32), nullable=False),
        sa.Column("step_graph_json", _jsonb(), nullable=False),
        sa.Column("artifact_contract_json", _jsonb(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("supersedes_version_id", sa.String(length=96)),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index(
        "uq_current_agent_flow_versions",
        "agent_flow_versions",
        ["owner_id", "environment", "flow_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true and lifecycle = 'active'"),
    )
    op.create_index(
        "ix_agent_flow_versions_lookup",
        "agent_flow_versions",
        [
            "owner_id",
            "environment",
            "flow_id",
            "valid_from",
            "valid_to",
            "available_at",
        ],
    )

    op.create_table(
        "quant_agent_profile_versions",
        sa.Column("version_id", sa.String(length=96), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("profile_key", sa.String(length=96), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_family", sa.String(length=96), nullable=False),
        sa.Column("strategy_version", sa.String(length=96), nullable=False),
        sa.Column("model_family", sa.String(length=96), nullable=False),
        sa.Column("candidate_universe", sa.String(length=96), nullable=False),
        sa.Column("score_name", sa.String(length=128), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("score_temperature", sa.Float(), nullable=False),
        sa.Column("max_stock_exposure", sa.Float(), nullable=False),
        sa.Column("min_cash", sa.Float(), nullable=False),
        sa.Column("exposure_mode", sa.String(length=64), nullable=False),
        sa.Column("daily_stop_loss", sa.Float(), nullable=False),
        sa.Column("daily_drawdown_stop", sa.Float(), nullable=False),
        sa.Column("cash_annual", sa.Float(), nullable=False),
        sa.Column("required_feature_groups", _jsonb(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("supersedes_version_id", sa.String(length=96)),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index(
        "uq_current_quant_agent_profile_versions",
        "quant_agent_profile_versions",
        ["owner_id", "environment", "profile_key"],
        unique=True,
        postgresql_where=sa.text("is_current = true and lifecycle = 'active'"),
    )
    op.create_index(
        "ix_quant_agent_profile_versions_lookup",
        "quant_agent_profile_versions",
        [
            "owner_id",
            "environment",
            "profile_key",
            "valid_from",
            "valid_to",
            "available_at",
        ],
    )

    op.create_table(
        "config_resolution_snapshots",
        sa.Column("snapshot_id", sa.String(length=96), primary_key=True),
        sa.Column("run_id", sa.String(length=96), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_config_resolution_snapshots_run_id",
        "config_resolution_snapshots",
        ["run_id"],
    )
    op.create_table(
        "config_resolution_snapshot_entries",
        sa.Column("entry_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(length=96),
            sa.ForeignKey(
                "config_resolution_snapshots.snapshot_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("config_key", sa.String(length=128), nullable=False),
        sa.Column("version_id", sa.String(length=96), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
    )
    op.create_index(
        "ix_config_resolution_snapshot_entries_snapshot_id",
        "config_resolution_snapshot_entries",
        ["snapshot_id"],
    )
    op.create_index(
        "uq_config_resolution_snapshot_entries",
        "config_resolution_snapshot_entries",
        ["snapshot_id", "domain", "config_key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop runtime config domain tables and resolution snapshots."""
    op.drop_index(
        "uq_config_resolution_snapshot_entries",
        table_name="config_resolution_snapshot_entries",
    )
    op.drop_index(
        "ix_config_resolution_snapshot_entries_snapshot_id",
        table_name="config_resolution_snapshot_entries",
    )
    op.drop_table("config_resolution_snapshot_entries")
    op.drop_index(
        "ix_config_resolution_snapshots_run_id",
        table_name="config_resolution_snapshots",
    )
    op.drop_table("config_resolution_snapshots")
    op.drop_index(
        "ix_quant_agent_profile_versions_lookup",
        table_name="quant_agent_profile_versions",
    )
    op.drop_index(
        "uq_current_quant_agent_profile_versions",
        table_name="quant_agent_profile_versions",
    )
    op.drop_table("quant_agent_profile_versions")
    op.drop_index(
        "ix_agent_flow_versions_lookup",
        table_name="agent_flow_versions",
    )
    op.drop_index(
        "uq_current_agent_flow_versions",
        table_name="agent_flow_versions",
    )
    op.drop_table("agent_flow_versions")
