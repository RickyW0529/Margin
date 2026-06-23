"""Add v0.2 point-in-time data warehouse tables.

Revision ID: 20260622_0010_data_warehouse
Revises: 20260619_0009_audit
Create Date: 2026-06-22 17:15:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260622_0010_data_warehouse"
down_revision: str | None = "20260619_0009_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """upgrade."""
    op.create_table(
        "provider_endpoints",
        Column("endpoint_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("code", String(96), nullable=False),
        Column("domain", String(48), nullable=False),
        Column("enabled", Boolean, nullable=False, default=True),
        Column("backfill_policy", JSONB, nullable=False),
        Column("revision_lookback_days", Integer, nullable=False, default=0),
        Column("rate_limit_policy", JSONB, nullable=False),
        Column("schema_version", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("provider", "code", name="uq_provider_endpoint_provider_code"),
    )
    op.create_index("ix_provider_endpoints_domain", "provider_endpoints", ["domain"])

    op.create_table(
        "data_sync_runs",
        Column("run_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=True),
        Column("status", String(32), nullable=False),
        Column("requested_by", String(64), nullable=False, default="system"),
        Column("endpoint_count", Integer, nullable=False, default=0),
        Column("completed_count", Integer, nullable=False, default=0),
        Column("failed_count", Integer, nullable=False, default=0),
        Column("input_hash", String(96), nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=True),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("error_summary", JSONB, nullable=False, default={}),
    )
    op.create_index("ix_data_sync_runs_status", "data_sync_runs", ["status", "created_at"])
    op.create_index("ix_data_sync_runs_provider", "data_sync_runs", ["provider", "created_at"])

    op.create_table(
        "data_sync_work_items",
        Column("work_item_id", String(64), primary_key=True),
        Column(
            "run_id",
            String(64),
            ForeignKey("data_sync_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column(
            "endpoint_id",
            String(64),
            ForeignKey("provider_endpoints.endpoint_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        Column("status", String(32), nullable=False),
        Column("cursor_before", Text, nullable=True),
        Column("cursor_after", Text, nullable=True),
        Column("attempt_count", Integer, nullable=False, default=0),
        Column("next_attempt_at", DateTime(timezone=True), nullable=True),
        Column("claimed_by", String(96), nullable=True),
        Column("claimed_at", DateTime(timezone=True), nullable=True),
        Column("last_error_code", String(64), nullable=True),
        Column("last_error_message", Text, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        UniqueConstraint("run_id", "endpoint_id", "cursor_before", name="uq_data_work_item"),
    )
    op.create_index(
        "ix_data_work_items_claim",
        "data_sync_work_items",
        ["status", "next_attempt_at", "created_at"],
    )

    op.create_table(
        "raw_data_snapshots",
        Column("snapshot_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("endpoint_code", String(96), nullable=False),
        Column("payload_hash", String(96), nullable=False),
        Column("storage_uri", Text, nullable=False),
        Column("compression", String(24), nullable=False),
        Column("raw_size", BigInteger, nullable=False),
        Column("compressed_size", BigInteger, nullable=False),
        Column("fetched_at", DateTime(timezone=True), nullable=False),
        Column("available_at", DateTime(timezone=True), nullable=True),
        Column("retention_class", String(32), nullable=False),
        Column("payload_metadata", JSONB, nullable=False, default={}),
        UniqueConstraint("provider", "endpoint_code", "payload_hash", name="uq_raw_data_payload"),
    )
    op.create_index("ix_raw_data_snapshots_payload_hash", "raw_data_snapshots", ["payload_hash"])

    op.create_table(
        "source_schema_fields",
        Column("field_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("endpoint_code", String(96), nullable=False),
        Column("field_name", String(128), nullable=False),
        Column("inferred_type", String(48), nullable=False),
        Column("status", String(32), nullable=False),
        Column("first_seen_at", DateTime(timezone=True), nullable=False),
        Column("last_seen_at", DateTime(timezone=True), nullable=False),
        Column("consecutive_missing_count", Integer, nullable=False, default=0),
        Column("type_change_count", Integer, nullable=False, default=0),
        Column("sample_values", JSONB, nullable=False, default=[]),
        UniqueConstraint("provider", "endpoint_code", "field_name", name="uq_source_schema_field"),
    )
    op.create_index("ix_source_schema_fields_status", "source_schema_fields", ["status"])

    op.create_table(
        "indicator_definitions",
        Column("indicator_id", String(96), primary_key=True),
        Column("version", String(64), primary_key=True),
        Column("domain", String(48), nullable=False),
        Column("name", Text, nullable=False),
        Column("value_type", String(32), nullable=False),
        Column("unit", String(32), nullable=True),
        Column("direction", String(16), nullable=True),
        Column("required_for_quant", Boolean, nullable=False, default=False),
        Column("definition", JSONB, nullable=False, default={}),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "provider_indicator_mappings",
        Column("mapping_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("endpoint_code", String(96), nullable=False),
        Column("source_field", String(128), nullable=False),
        Column("indicator_id", String(96), nullable=False),
        Column("indicator_version", String(64), nullable=False),
        Column("mapping_version", String(64), nullable=False),
        Column("transform", JSONB, nullable=False, default={}),
        Column("active", Boolean, nullable=False, default=True),
        UniqueConstraint(
            "provider",
            "endpoint_code",
            "source_field",
            "mapping_version",
            name="uq_provider_indicator_mapping",
        ),
    )

    op.create_table(
        "standardized_indicator_facts",
        Column("fact_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("provider_fact_id", String(128), nullable=False),
        Column("endpoint_code", String(96), nullable=False),
        Column("security_id", String(32), nullable=False),
        Column("indicator_id", String(96), nullable=False),
        Column("indicator_version", String(64), nullable=False),
        Column("event_at", DateTime(timezone=True), nullable=False),
        Column("published_at", DateTime(timezone=True), nullable=True),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("fetched_at", DateTime(timezone=True), nullable=False),
        Column("revised_at", DateTime(timezone=True), nullable=True),
        Column("numeric_value", Numeric(28, 10), nullable=True),
        Column("text_value", Text, nullable=True),
        Column("json_value", JSONB, nullable=True),
        Column("unit", String(32), nullable=True),
        Column("quality_score", Numeric(6, 5), nullable=False),
        Column("mapping_version", String(64), nullable=False),
        Column(
            "raw_snapshot_id",
            String(64),
            ForeignKey("raw_data_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        Column("lineage", JSONB, nullable=False, default={}),
        UniqueConstraint("provider", "provider_fact_id", name="uq_standardized_provider_fact"),
    )
    op.create_index(
        "ix_indicator_facts_security_indicator",
        "standardized_indicator_facts",
        ["security_id", "indicator_id", "event_at"],
    )
    op.create_index(
        "ix_indicator_facts_available",
        "standardized_indicator_facts",
        ["available_at"],
    )

    op.create_table(
        "canonical_indicator_values",
        Column("canonical_id", String(64), primary_key=True),
        Column("security_id", String(32), nullable=False),
        Column("indicator_id", String(96), nullable=False),
        Column("indicator_version", String(64), nullable=False),
        Column("decision_at", DateTime(timezone=True), nullable=False),
        Column(
            "selected_fact_id",
            String(64),
            ForeignKey("standardized_indicator_facts.fact_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        Column("candidate_fact_ids", JSONB, nullable=False),
        Column("status", String(32), nullable=False),
        Column("numeric_value", Numeric(28, 10), nullable=True),
        Column("text_value", Text, nullable=True),
        Column("json_value", JSONB, nullable=True),
        Column("confidence", Numeric(6, 5), nullable=False),
        Column("resolver_version", String(64), nullable=False),
        Column("resolver_hash", String(96), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint(
            "security_id",
            "indicator_id",
            "decision_at",
            "resolver_version",
            name="uq_canonical_value_resolver",
        ),
    )
    op.create_index(
        "ix_canonical_values_security_indicator",
        "canonical_indicator_values",
        ["security_id", "indicator_id"],
    )
    op.create_index(
        "ix_canonical_values_decision_at",
        "canonical_indicator_values",
        ["decision_at"],
    )

    op.create_table(
        "securities",
        Column("security_id", String(32), primary_key=True),
        Column("symbol", String(32), nullable=False),
        Column("name", Text, nullable=False),
        Column("exchange", String(16), nullable=False),
        Column("listed_at", Date, nullable=True),
        Column("delisted_at", Date, nullable=True),
        Column("security_type", String(32), nullable=False, default="stock"),
        Column("system_from", DateTime(timezone=True), nullable=False),
        Column("system_to", DateTime(timezone=True), nullable=True),
        Column("raw_lineage_ids", JSONB, nullable=False, default=[]),
    )
    op.create_index("ix_securities_symbol", "securities", ["symbol"])

    op.create_table(
        "security_provider_identifiers",
        Column("identifier_id", String(64), primary_key=True),
        Column(
            "security_id",
            String(32),
            ForeignKey("securities.security_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("provider", String(64), nullable=False),
        Column("provider_symbol", String(64), nullable=False),
        Column("valid_from", Date, nullable=False),
        Column("valid_to", Date, nullable=True),
        Column("system_from", DateTime(timezone=True), nullable=False),
        Column("system_to", DateTime(timezone=True), nullable=True),
        UniqueConstraint(
            "provider",
            "provider_symbol",
            "valid_from",
            "system_from",
            name="uq_security_provider_identifier",
        ),
    )
    op.create_index(
        "ix_security_provider_identifiers_security",
        "security_provider_identifiers",
        ["security_id"],
    )

    op.create_table(
        "security_industry_memberships",
        Column("membership_id", String(64), primary_key=True),
        Column(
            "security_id",
            String(32),
            ForeignKey("securities.security_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("taxonomy", String(64), nullable=False),
        Column("industry_code", String(64), nullable=False),
        Column("industry_name", Text, nullable=False),
        Column("valid_from", Date, nullable=False),
        Column("valid_to", Date, nullable=True),
        Column("system_from", DateTime(timezone=True), nullable=False),
        Column("system_to", DateTime(timezone=True), nullable=True),
        Column("source", String(96), nullable=False),
        Column("quality", String(32), nullable=False),
        Column("raw_lineage_ids", JSONB, nullable=False, default=[]),
        UniqueConstraint(
            "security_id",
            "taxonomy",
            "valid_from",
            "system_from",
            name="uq_security_industry_membership",
        ),
    )
    op.create_index(
        "ix_security_industry_lookup",
        "security_industry_memberships",
        ["security_id", "taxonomy", "valid_from", "system_from"],
    )

    op.create_table(
        "corporate_actions",
        Column("action_id", String(64), primary_key=True),
        Column(
            "security_id",
            String(32),
            ForeignKey("securities.security_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("action_type", String(48), nullable=False),
        Column("announcement_date", Date, nullable=True),
        Column("ex_date", Date, nullable=True),
        Column("record_date", Date, nullable=True),
        Column("payable_date", Date, nullable=True),
        Column("cash_amount", Numeric(28, 10), nullable=True),
        Column("share_ratio", Numeric(28, 10), nullable=True),
        Column("published_at", DateTime(timezone=True), nullable=True),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("fetched_at", DateTime(timezone=True), nullable=False),
        Column(
            "raw_snapshot_id",
            String(64),
            ForeignKey("raw_data_snapshots.snapshot_id", ondelete="SET NULL"),
            nullable=True,
        ),
        Column("payload", JSONB, nullable=False, default={}),
        UniqueConstraint(
            "security_id",
            "action_type",
            "ex_date",
            "available_at",
            name="uq_corporate_action_pit",
        ),
    )
    op.create_index(
        "ix_corporate_actions_security_available",
        "corporate_actions",
        ["security_id", "available_at"],
    )

    op.create_table(
        "adjusted_price_series",
        Column("adjusted_price_id", String(64), primary_key=True),
        Column(
            "security_id",
            String(32),
            ForeignKey("securities.security_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("trade_date", Date, nullable=False),
        Column("decision_at", DateTime(timezone=True), nullable=False),
        Column("close", Numeric(28, 10), nullable=False),
        Column("adj_close", Numeric(28, 10), nullable=False),
        Column("adjustment_factor", Numeric(28, 10), nullable=False),
        Column("adjustment_policy_version", String(64), nullable=False),
        Column("input_hash", String(96), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint(
            "security_id",
            "trade_date",
            "decision_at",
            "adjustment_policy_version",
            name="uq_adjusted_price_series",
        ),
    )
    op.create_index(
        "ix_adjusted_price_series_security",
        "adjusted_price_series",
        ["security_id", "decision_at"],
    )

    op.create_table(
        "data_quality_events",
        Column("event_id", String(64), primary_key=True),
        Column("security_id", String(32), nullable=True),
        Column("indicator_id", String(96), nullable=True),
        Column("issue_type", String(48), nullable=False),
        Column("severity", String(24), nullable=False),
        Column("message", Text, nullable=False),
        Column("observed", JSONB, nullable=False, default={}),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_data_quality_events_security",
        "data_quality_events",
        ["security_id", "created_at"],
    )

    op.create_table(
        "data_freshness_states",
        Column("freshness_id", String(64), primary_key=True),
        Column("provider", String(64), nullable=False),
        Column("endpoint_code", String(96), nullable=False),
        Column("as_of_date", Date, nullable=False),
        Column("expected_at", DateTime(timezone=True), nullable=True),
        Column("observed_at", DateTime(timezone=True), nullable=True),
        Column("status", String(32), nullable=False),
        Column("lag_seconds", Integer, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("provider", "endpoint_code", "as_of_date", name="uq_data_freshness"),
    )
    op.create_index("ix_data_freshness_status", "data_freshness_states", ["status", "as_of_date"])

    op.create_table(
        "retention_deletion_audits",
        Column("audit_id", String(64), primary_key=True),
        Column("object_type", String(48), nullable=False),
        Column("object_id", String(96), nullable=False),
        Column("decision", String(32), nullable=False),
        Column("reason", Text, nullable=False),
        Column("reference_count", Integer, nullable=False, default=0),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """downgrade."""
    for table_name in (
        "retention_deletion_audits",
        "data_freshness_states",
        "data_quality_events",
        "adjusted_price_series",
        "corporate_actions",
        "security_industry_memberships",
        "security_provider_identifiers",
        "securities",
        "canonical_indicator_values",
        "standardized_indicator_facts",
        "provider_indicator_mappings",
        "indicator_definitions",
        "source_schema_fields",
        "raw_data_snapshots",
        "data_sync_work_items",
        "data_sync_runs",
        "provider_endpoints",
    ):
        op.drop_table(table_name)
