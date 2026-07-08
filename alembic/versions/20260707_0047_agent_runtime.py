"""Add v0.4 agent runtime context store tables.

Revision ID: 20260707_0047_agent_runtime
Revises: 20260702_0046_run_metadata
Create Date: 2026-07-07 00:47:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260707_0047_agent_runtime"
down_revision = "20260702_0046_run_metadata"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    """Return a PostgreSQL JSONB column type."""
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create v0.4 agent runtime context store tables."""
    op.create_table(
        "agent_runtime_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("permission_mode", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_runtime_runs_type_started",
        "agent_runtime_runs",
        ["run_type", "started_at"],
    )

    op.create_table(
        "agent_runtime_steps",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("step_id", sa.String(length=64), primary_key=True),
        sa.Column("expert_agent_name", sa.String(length=96), nullable=False),
        sa.Column("skill_id", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runtime_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_agent_runtime_steps_run_created",
        "agent_runtime_steps",
        ["run_id", "created_at"],
    )

    op.create_table(
        "agent_runtime_artifacts",
        sa.Column("artifact_id", sa.String(length=96), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=96), nullable=False),
        sa.Column("producer_agent", sa.String(length=96), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column(
            "source_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_refs",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runtime_runs.run_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_agent_runtime_artifacts_run_type",
        "agent_runtime_artifacts",
        ["run_id", "artifact_type"],
    )
    op.create_index(
        "ix_agent_runtime_artifacts_created",
        "agent_runtime_artifacts",
        ["run_id", "created_at"],
    )

    op.create_table(
        "agent_runtime_guardrail_decisions",
        sa.Column("decision_id", sa.String(length=96), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("evaluation_summary", sa.Text(), nullable=False),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_runtime_guardrails_run_stage",
        "agent_runtime_guardrail_decisions",
        ["run_id", "stage"],
    )
    op.create_index(
        "ix_agent_runtime_guardrails_created",
        "agent_runtime_guardrail_decisions",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    """Drop v0.4 agent runtime context store tables."""
    op.drop_index(
        "ix_agent_runtime_guardrails_created",
        table_name="agent_runtime_guardrail_decisions",
    )
    op.drop_index(
        "ix_agent_runtime_guardrails_run_stage",
        table_name="agent_runtime_guardrail_decisions",
    )
    op.drop_table("agent_runtime_guardrail_decisions")
    op.drop_index(
        "ix_agent_runtime_artifacts_created",
        table_name="agent_runtime_artifacts",
    )
    op.drop_index(
        "ix_agent_runtime_artifacts_run_type",
        table_name="agent_runtime_artifacts",
    )
    op.drop_table("agent_runtime_artifacts")
    op.drop_index(
        "ix_agent_runtime_steps_run_created",
        table_name="agent_runtime_steps",
    )
    op.drop_table("agent_runtime_steps")
    op.drop_index(
        "ix_agent_runtime_runs_type_started",
        table_name="agent_runtime_runs",
    )
    op.drop_table("agent_runtime_runs")
