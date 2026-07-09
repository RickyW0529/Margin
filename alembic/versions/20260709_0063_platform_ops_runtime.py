"""Add formal platform and ops runtime tables.

Revision ID: 20260709_0063_platform_ops
Revises: 20260709_0062_prompts
Create Date: 2026-07-09 17:45:00

Creates:
- platform.idempotency_keys
- platform.runtime_environments
- platform.config_resolution_snapshots
- platform.outbox_events
- platform.dead_letter_queue
- ops.backfill_campaigns
- ops.backfill_partitions
- ops.backfill_quality_reports
- ops.system_health_snapshots
- ops.data_freshness_states
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260709_0063_platform_ops"
down_revision = "20260709_0062_prompts"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return PostgreSQL JSONB with text astype."""
    return postgresql.JSONB(astext_type=sa.Text())


def _text_array() -> postgresql.ARRAY:
    """Return a PostgreSQL text array type."""
    return postgresql.ARRAY(sa.Text())


def upgrade() -> None:
    """Create formal platform and ops runtime tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")
    _create_platform_tables()
    _create_ops_tables()


def _create_platform_tables() -> None:
    """Create platform runtime tables."""
    op.create_table(
        "idempotency_keys",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_hash", sa.Text()),
        sa.Column("response_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_index(
        "ix_idempotency_keys_expires",
        "idempotency_keys",
        ["expires_at"],
        schema="platform",
    )

    op.create_table(
        "runtime_environments",
        sa.Column("environment_id", sa.Text(), primary_key=True),
        sa.Column("environment_name", sa.Text(), nullable=False),
        sa.Column("app_version", sa.Text()),
        sa.Column("git_commit", sa.Text()),
        sa.Column("python_version", sa.Text()),
        sa.Column("node_version", sa.Text()),
        sa.Column("database_url_hash", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="platform",
    )

    op.create_table(
        "config_resolution_snapshots",
        sa.Column("config_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text()),
        sa.Column("environment_id", sa.Text()),
        sa.Column("resolved_config_json", _jsonb(), nullable=False),
        sa.Column("resolved_config_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="platform",
    )

    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        schema="platform",
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["status", "next_attempt_at"],
        schema="platform",
    )

    op.create_table(
        "dead_letter_queue",
        sa.Column("dlq_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("payload_redacted_json", _jsonb()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="platform",
    )


def _create_ops_tables() -> None:
    """Create ops runtime tables."""
    op.create_table(
        "backfill_campaigns",
        sa.Column("campaign_id", sa.Text(), primary_key=True),
        sa.Column("campaign_name", sa.Text(), nullable=False),
        sa.Column("years", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("providers", _text_array(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("endpoint_plan_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("mode", sa.Text(), nullable=False, server_default="dry_run"),
        sa.Column("created_by_run_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="ops",
    )

    op.create_table(
        "backfill_partitions",
        sa.Column("partition_id", sa.Text(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Text(),
            sa.ForeignKey("ops.backfill_campaigns.campaign_id"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("partition_start", sa.Date(), nullable=False),
        sa.Column("partition_end", sa.Date(), nullable=False),
        sa.Column("params_json", _jsonb(), nullable=False),
        sa.Column("params_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.Text()),
        sa.Column(
            "raw_snapshot_refs",
            _text_array(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("quality_report_ref", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "provider_name",
            "endpoint_name",
            "params_hash",
            name="uq_backfill_partition_params",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_backfill_partitions_status",
        "backfill_partitions",
        ["status", "provider_name", "endpoint_name"],
        schema="ops",
    )

    op.create_table(
        "backfill_quality_reports",
        sa.Column("quality_report_id", sa.Text(), primary_key=True),
        sa.Column("campaign_id", sa.Text(), nullable=False),
        sa.Column("partition_id", sa.Text()),
        sa.Column("provider_name", sa.Text()),
        sa.Column("endpoint_name", sa.Text()),
        sa.Column("coverage_start", sa.Date()),
        sa.Column("coverage_end", sa.Date()),
        sa.Column("expected_rows", sa.Integer()),
        sa.Column("actual_rows", sa.Integer()),
        sa.Column("missing_dates", _text_array(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("duplicate_key_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_drift_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("report_json", _jsonb(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="ops",
    )

    op.create_table(
        "system_health_snapshots",
        sa.Column("health_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("component_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("metrics_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="ops",
    )

    op.create_table(
        "data_freshness_states",
        sa.Column("freshness_state_id", sa.Text(), primary_key=True),
        sa.Column("dataset_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text()),
        sa.Column("latest_available_date", sa.Date()),
        sa.Column("latest_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("stale_after_seconds", sa.Integer()),
        sa.Column("freshness_status", sa.Text(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="ops",
    )


def downgrade() -> None:
    """Drop formal platform and ops runtime tables."""
    op.drop_table("data_freshness_states", schema="ops")
    op.drop_table("system_health_snapshots", schema="ops")
    op.drop_table("backfill_quality_reports", schema="ops")
    op.drop_table("backfill_partitions", schema="ops")
    op.drop_table("backfill_campaigns", schema="ops")
    op.drop_table("dead_letter_queue", schema="platform")
    op.drop_index("ix_outbox_pending", table_name="outbox_events", schema="platform")
    op.drop_table("outbox_events", schema="platform")
    op.drop_table("config_resolution_snapshots", schema="platform")
    op.drop_table("runtime_environments", schema="platform")
    op.drop_index(
        "ix_idempotency_keys_expires",
        table_name="idempotency_keys",
        schema="platform",
    )
    op.drop_table("idempotency_keys", schema="platform")
