"""Add v0.2 durable orchestration, capacity, outbox, and smoke tables.

Revision ID: 20260622_0018_deploy_audit
Revises: 20260622_0017_config_audit
Create Date: 2026-06-22 21:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260622_0018_deploy_audit"
down_revision = "20260622_0017_config_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """upgrade."""
    op.create_table(
        "orchestration_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64)),
        sa.Column("scope_hash", sa.String(length=96)),
        sa.Column("idempotency_key_hash", sa.String(length=96)),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column(
            "degradation_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_orchestration_runs_type_created",
        "orchestration_runs",
        ["run_type", "created_at"],
    )
    op.create_index(
        "ix_orchestration_runs_state_created",
        "orchestration_runs",
        ["state", "created_at"],
    )
    op.create_index(
        "uq_orchestration_runs_idempotency",
        "orchestration_runs",
        ["run_type", "idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text("idempotency_key_hash IS NOT NULL"),
    )

    op.create_table(
        "orchestration_step_attempts",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_id", sa.String(length=96), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("state_seq", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("output_ref", sa.String(length=256)),
        sa.Column("error_code", sa.String(length=96)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("previous_event_id", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_no >= 1", name="ck_step_attempt_positive"),
        sa.CheckConstraint("state_seq >= 0", name="ck_step_state_seq_nonnegative"),
        sa.UniqueConstraint(
            "run_id",
            "step_id",
            "attempt_no",
            "state_seq",
            name="uq_orchestration_step_attempt_sequence",
        ),
    )
    op.create_index(
        "ix_orchestration_step_claim",
        "orchestration_step_attempts",
        ["state", "lease_expires_at", "retry_after"],
    )
    op.create_index(
        "ix_orchestration_step_latest",
        "orchestration_step_attempts",
        ["run_id", "step_id", "attempt_no", "state_seq"],
    )

    op.create_table(
        "capacity_limit_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("limit_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("limit_type", sa.String(length=32), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("max_count", sa.Integer()),
        sa.Column("max_tokens", sa.Integer()),
        sa.Column("max_cost", sa.Numeric(20, 8)),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("window_seconds > 0", name="ck_capacity_window_positive"),
        sa.UniqueConstraint("limit_key", "version", name="uq_capacity_limit_version"),
    )

    op.create_table(
        "provider_capacity_counters",
        sa.Column("counter_id", sa.String(length=64), primary_key=True),
        sa.Column("limit_key", sa.String(length=128), nullable=False),
        sa.Column(
            "limit_version_id",
            sa.String(length=64),
            sa.ForeignKey("capacity_limit_versions.version_id"),
            nullable=False,
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "request_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_amount",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="ck_capacity_count_nonnegative"),
        sa.CheckConstraint("token_count >= 0", name="ck_capacity_tokens_nonnegative"),
        sa.UniqueConstraint(
            "limit_key",
            "window_started_at",
            name="uq_provider_capacity_window",
        ),
    )

    op.create_table(
        "transactional_outbox",
        sa.Column("outbox_id", sa.String(length=64), primary_key=True),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=192), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error_code", sa.String(length=96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_nonnegative"),
        sa.UniqueConstraint(
            "topic",
            "idempotency_key",
            name="uq_outbox_topic_idempotency",
        ),
    )
    op.create_index(
        "ix_transactional_outbox_claim",
        "transactional_outbox",
        ["topic", "state", "available_at"],
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
    op.create_index(
        "ix_idempotency_expiry",
        "idempotency_records",
        ["expires_at"],
    )

    op.create_table(
        "smoke_run_records",
        sa.Column("smoke_run_id", sa.String(length=64), primary_key=True),
        sa.Column("stage", sa.String(length=96), nullable=False),
        sa.Column("provider", sa.String(length=64)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_blocker", sa.String(length=48)),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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


def downgrade() -> None:
    """downgrade."""
    op.drop_index("ix_smoke_run_status_started", table_name="smoke_run_records")
    op.drop_index("ix_smoke_run_stage_started", table_name="smoke_run_records")
    op.drop_table("smoke_run_records")
    op.drop_index("ix_idempotency_expiry", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index(
        "ix_transactional_outbox_claim",
        table_name="transactional_outbox",
    )
    op.drop_table("transactional_outbox")
    op.drop_table("provider_capacity_counters")
    op.drop_table("capacity_limit_versions")
    op.drop_index(
        "ix_orchestration_step_latest",
        table_name="orchestration_step_attempts",
    )
    op.drop_index(
        "ix_orchestration_step_claim",
        table_name="orchestration_step_attempts",
    )
    op.drop_table("orchestration_step_attempts")
    op.drop_index(
        "uq_orchestration_runs_idempotency",
        table_name="orchestration_runs",
    )
    op.drop_index(
        "ix_orchestration_runs_state_created",
        table_name="orchestration_runs",
    )
    op.drop_index(
        "ix_orchestration_runs_type_created",
        table_name="orchestration_runs",
    )
    op.drop_table("orchestration_runs")
