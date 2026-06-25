"""Remove dead ORM tables not used by current runtime paths.

Revision ID: 20260625_0044_dead_schema
Revises: 20260625_0043_quant_feature_mart
Create Date: 2026-06-25 00:44:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260625_0044_dead_schema"
down_revision = "20260625_0043_quant_feature_mart"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Drop tables that had ORM/migration definitions but no runtime repository."""
    for table_name in (
        "smoke_run_records",
        "idempotency_records",
        "confidence_components",
        "valuation_refresh_steps",
        "valuation_refresh_runs",
        "research_refresh_events",
        "universe_memberships",
        "universe_snapshots",
        "universe_versions",
        "universe_definitions",
        "provider_indicator_mappings",
        "indicator_definitions",
    ):
        op.drop_table(table_name)


def downgrade() -> None:
    """Recreate the removed tables for downgrade compatibility."""
    op.create_table(
        "indicator_definitions",
        sa.Column("indicator_id", sa.String(length=96), primary_key=True),
        sa.Column("version", sa.String(length=64), primary_key=True),
        sa.Column("domain", sa.String(length=48), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=32)),
        sa.Column("direction", sa.String(length=16)),
        sa.Column("required_for_quant", sa.Boolean(), nullable=False, default=False),
        sa.Column("definition", _jsonb(), nullable=False, default={}),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "provider_indicator_mappings",
        sa.Column("mapping_id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("endpoint_code", sa.String(length=96), nullable=False),
        sa.Column("source_field", sa.String(length=128), nullable=False),
        sa.Column("indicator_id", sa.String(length=96), nullable=False),
        sa.Column("indicator_version", sa.String(length=64), nullable=False),
        sa.Column("mapping_version", sa.String(length=64), nullable=False),
        sa.Column("transform", _jsonb(), nullable=False, default={}),
        sa.Column("active", sa.Boolean(), nullable=False, default=True),
        sa.UniqueConstraint(
            "provider",
            "endpoint_code",
            "source_field",
            "mapping_version",
            name="uq_provider_indicator_mapping",
        ),
    )

    op.create_table(
        "universe_definitions",
        sa.Column("definition_id", sa.String(length=64), primary_key=True),
        sa.Column("universe_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("rule_code", sa.String(length=128), nullable=False),
        sa.Column("rule_config", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_universe_definitions_universe_code",
        "universe_definitions",
        ["universe_code"],
    )

    op.create_table(
        "universe_versions",
        sa.Column("universe_version_id", sa.String(length=64), primary_key=True),
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("universe_code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_to", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "ix_universe_versions_definition_id",
        "universe_versions",
        ["definition_id"],
    )
    op.create_index(
        "ix_universe_versions_code_system",
        "universe_versions",
        ["universe_code", "system_from"],
    )

    op.create_table(
        "universe_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("universe_code", sa.String(length=64), nullable=False),
        sa.Column("universe_version_id", sa.String(length=64), nullable=False),
        sa.Column("business_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("security_ids", _jsonb(), nullable=False),
        sa.Column(
            "membership_ids",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_universe_snapshots_universe_version_id",
        "universe_snapshots",
        ["universe_version_id"],
    )
    op.create_index(
        "ix_universe_snapshots_code_time",
        "universe_snapshots",
        ["universe_code", "business_at", "known_at"],
    )

    op.create_table(
        "universe_memberships",
        sa.Column("membership_id", sa.String(length=64), primary_key=True),
        sa.Column("universe_code", sa.String(length=64), nullable=False),
        sa.Column("universe_version_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_to", sa.DateTime(timezone=True)),
        sa.Column("weight", sa.Float()),
        sa.Column("rank", sa.Integer()),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column(
            "raw_lineage_ids",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("metadata_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "ix_universe_memberships_universe_version_id",
        "universe_memberships",
        ["universe_version_id"],
    )
    op.create_index(
        "ix_universe_memberships_security_id",
        "universe_memberships",
        ["security_id"],
    )
    op.create_index(
        "ix_universe_memberships_code_valid_system",
        "universe_memberships",
        ["universe_code", "valid_from", "system_from"],
    )
    op.create_index(
        "ix_universe_memberships_security_time",
        "universe_memberships",
        ["security_id", "valid_from"],
    )

    op.create_table(
        "research_refresh_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("refresh_run_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_refresh_events_refresh_run_id",
        "research_refresh_events",
        ["refresh_run_id"],
    )

    op.create_table(
        "valuation_refresh_runs",
        sa.Column("refresh_run_id", sa.String(length=64), primary_key=True),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_valuation_refresh_runs_scope_decision",
        "valuation_refresh_runs",
        ["scope_version_id", "decision_at"],
    )

    op.create_table(
        "valuation_refresh_steps",
        sa.Column("step_event_id", sa.String(length=64), primary_key=True),
        sa.Column("refresh_run_id", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("output_ref", sa.String(length=256)),
        sa.Column("error_code", sa.String(length=128)),
    )
    op.create_index(
        "ix_valuation_refresh_steps_refresh_run_id",
        "valuation_refresh_steps",
        ["refresh_run_id"],
    )

    op.create_table(
        "confidence_components",
        sa.Column("component_id", sa.String(length=64), primary_key=True),
        sa.Column("assessment_id", sa.String(length=64), nullable=False),
        sa.Column("component_name", sa.String(length=128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_confidence_components_assessment_id",
        "confidence_components",
        ["assessment_id"],
    )

    op.create_table(
        "idempotency_records",
        sa.Column("record_id", sa.String(length=64), primary_key=True),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=96), nullable=False),
        sa.Column("request_hash", sa.String(length=96), nullable=False),
        sa.Column("response_ref", sa.String(length=256)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scope", "key_hash", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_expiry", "idempotency_records", ["expires_at"])

    op.create_table(
        "smoke_run_records",
        sa.Column("smoke_run_id", sa.String(length=64), primary_key=True),
        sa.Column("stage", sa.String(length=96), nullable=False),
        sa.Column("provider", sa.String(length=64)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_blocker", sa.String(length=48)),
        sa.Column("detail_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(length=96)),
        sa.Column("redacted_error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_smoke_run_stage_started",
        "smoke_run_records",
        ["stage", "started_at"],
    )
    op.create_index(
        "ix_smoke_run_status_started",
        "smoke_run_records",
        ["status", "started_at"],
    )
