"""Add v0.2 valuation discovery tables.

Revision ID: 20260622_0021_valuation
Revises: 20260622_0020_step_input
Create Date: 2026-06-22 22:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0021_valuation"
down_revision = "20260622_0020_step_input"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """jsonb."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """upgrade."""
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
    op.create_index("ix_universe_versions_definition_id", "universe_versions", ["definition_id"])
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
    op.create_index("ix_universe_memberships_security_id", "universe_memberships", ["security_id"])
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
        "quant_input_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("universe_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("security_ids", _jsonb(), nullable=False),
        sa.Column("required_indicators", _jsonb(), nullable=False),
        sa.Column(
            "optional_indicators",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("fact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "missing_required",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("data_status", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quant_input_snapshots_scope_decision",
        "quant_input_snapshots",
        ["scope_version_id", "decision_at"],
    )

    op.create_table(
        "quant_input_snapshot_facts",
        sa.Column("fact_ref_id", sa.String(length=64), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("indicator_code", sa.String(length=128), nullable=False),
        sa.Column("fact_id", sa.String(length=96), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
    )
    op.create_index(
        "ix_quant_input_snapshot_facts_snapshot",
        "quant_input_snapshot_facts",
        ["snapshot_id", "security_id"],
    )

    op.create_table(
        "quant_screen_runs",
        sa.Column("quant_run_id", sa.String(length=64), primary_key=True),
        sa.Column("input_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_hash", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quant_screen_runs_input_snapshot_id",
        "quant_screen_runs",
        ["input_snapshot_id"],
    )
    op.create_index(
        "ix_quant_screen_runs_scope_decision",
        "quant_screen_runs",
        ["scope_version_id", "decision_at"],
    )

    op.create_table(
        "quant_screen_results",
        sa.Column("result_id", sa.String(length=64), primary_key=True),
        sa.Column("quant_run_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float()),
        sa.Column("value_score", sa.Float()),
        sa.Column("growth_score", sa.Float()),
        sa.Column("momentum_score", sa.Float()),
        sa.Column("risk_score", sa.Float()),
        sa.Column("screening_status", sa.String(length=32), nullable=False),
        sa.Column("data_status", sa.String(length=32), nullable=False),
        sa.Column("risk_flags", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "review_reasons",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("research_guardrail", sa.String(length=64), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "factor_details",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quant_screen_results_security_decision",
        "quant_screen_results",
        ["security_id", "created_at"],
    )
    op.create_index(
        "ix_quant_screen_results_run_status",
        "quant_screen_results",
        ["quant_run_id", "screening_status"],
    )

    op.create_table(
        "quant_factor_values",
        sa.Column("factor_value_id", sa.String(length=64), primary_key=True),
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("factor_group", sa.String(length=64), nullable=False),
        sa.Column("factor_name", sa.String(length=128), nullable=False),
        sa.Column("raw_value", sa.Float()),
        sa.Column("score", sa.Float()),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("detail_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "ix_quant_factor_values_result_group",
        "quant_factor_values",
        ["result_id", "factor_group"],
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
        "research_context_snapshots",
        sa.Column("context_snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_context_snapshots_security_scope",
        "research_context_snapshots",
        ["security_id", "scope_version_id"],
    )

    op.create_table(
        "valuation_assessments",
        sa.Column("assessment_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valuation_model", sa.String(length=128), nullable=False),
        sa.Column("intrinsic_value", sa.Float()),
        sa.Column("margin_of_safety", sa.Float()),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("evidence_refs", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_valuation_assessments_security_decision",
        "valuation_assessments",
        ["security_id", "decision_at"],
    )
    op.create_index(
        "ix_valuation_assessments_scope_decision",
        "valuation_assessments",
        ["scope_version_id", "decision_at"],
    )

    op.create_table(
        "valuation_assessment_evidence",
        sa.Column("edge_id", sa.String(length=64), primary_key=True),
        sa.Column("assessment_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=96), nullable=False),
        sa.Column("claim_id", sa.String(length=96)),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_valuation_assessment_evidence_assessment_id",
        "valuation_assessment_evidence",
        ["assessment_id"],
    )

    op.create_table(
        "effective_assessment_pointers",
        sa.Column("pointer_id", sa.String(length=64), primary_key=True),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("effective_assessment_id", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_by_assessment_id", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_effective_assessment_security_scope",
        "effective_assessment_pointers",
        ["security_id", "scope_version_id"],
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


def downgrade() -> None:
    """downgrade."""
    for table in (
        "confidence_components",
        "effective_assessment_pointers",
        "valuation_assessment_evidence",
        "valuation_assessments",
        "research_context_snapshots",
        "valuation_refresh_steps",
        "valuation_refresh_runs",
        "research_refresh_events",
        "quant_factor_values",
        "quant_screen_results",
        "quant_screen_runs",
        "quant_input_snapshot_facts",
        "quant_input_snapshots",
        "universe_memberships",
        "universe_snapshots",
        "universe_versions",
        "universe_definitions",
    ):
        op.drop_table(table)
