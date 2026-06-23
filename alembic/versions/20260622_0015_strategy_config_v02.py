"""Add v0.2 strategy configuration tables.

Revision ID: 20260622_0015_strategy_v02
Revises: 20260622_0010_data_warehouse
Create Date: 2026-06-22 18:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0015_strategy_v02"
down_revision = "20260622_0010_data_warehouse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.create_table(
        "provider_secret_versions",
        sa.Column("secret_version_id", sa.String(length=64), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("secret_name", sa.String(length=96), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("last_four", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_active_provider_secret_versions",
        "provider_secret_versions",
        ["provider_name", "secret_name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "provider_config_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "non_sensitive_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("secret_version_id", sa.String(length=64), nullable=True),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_active_provider_config_versions",
        "provider_config_versions",
        ["owner_id", "provider_name"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "universe_definition_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("universe_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column(
            "selection_rule",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "member_security_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_universe_definition_versions",
        "universe_definition_versions",
        ["owner_id", "universe_code"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "indicator_view_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column(
            "included_indicators",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded_indicators",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_indicator_view_versions",
        "indicator_view_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "quant_feature_set_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("required_indicators", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "optional_indicators",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("history_days", sa.Integer(), nullable=False),
        sa.Column("fallback_policy", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_quant_feature_set_versions",
        "quant_feature_set_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "quant_strategy_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_family", sa.String(length=64), nullable=False),
        sa.Column(
            "factor_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("calibration_report_id", sa.String(length=96), nullable=True),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_quant_strategy_versions",
        "quant_strategy_versions",
        ["owner_id", "strategy_family"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "user_style_prompt_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_name", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_user_style_prompt_versions",
        "user_style_prompt_versions",
        ["owner_id", "prompt_name"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.create_table(
        "research_scope_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("universe_version_id", sa.String(length=64), nullable=False),
        sa.Column("indicator_view_version_id", sa.String(length=64), nullable=False),
        sa.Column("quant_feature_set_version_id", sa.String(length=64), nullable=False),
        sa.Column("quant_strategy_version_id", sa.String(length=64), nullable=False),
        sa.Column("ai_prompt_version_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_rule_version", sa.String(length=64), nullable=False),
        sa.Column("tool_policy_version_id", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_config_version_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("scope_hash", sa.String(length=96), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_active_research_scope_versions",
        "research_scope_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )
    op.create_index("ix_research_scope_hash", "research_scope_versions", ["scope_hash"])

    op.create_table(
        "strategy_config_audits",
        sa.Column("audit_id", sa.String(length=64), primary_key=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_version_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """downgrade."""
    op.drop_table("strategy_config_audits")
    op.drop_index("ix_research_scope_hash", table_name="research_scope_versions")
    op.drop_index("uq_active_research_scope_versions", table_name="research_scope_versions")
    op.drop_table("research_scope_versions")
    op.drop_index("uq_active_user_style_prompt_versions", table_name="user_style_prompt_versions")
    op.drop_table("user_style_prompt_versions")
    op.drop_index("uq_active_quant_strategy_versions", table_name="quant_strategy_versions")
    op.drop_table("quant_strategy_versions")
    op.drop_index("uq_active_quant_feature_set_versions", table_name="quant_feature_set_versions")
    op.drop_table("quant_feature_set_versions")
    op.drop_index("uq_active_indicator_view_versions", table_name="indicator_view_versions")
    op.drop_table("indicator_view_versions")
    op.drop_index(
        "uq_active_universe_definition_versions",
        table_name="universe_definition_versions",
    )
    op.drop_table("universe_definition_versions")
    op.drop_index("uq_active_provider_config_versions", table_name="provider_config_versions")
    op.drop_table("provider_config_versions")
    op.drop_index("uq_active_provider_secret_versions", table_name="provider_secret_versions")
    op.drop_table("provider_secret_versions")
