"""Add the v0.2 AI delta review graph persistence schema.

Revision ID: 20260623_0030_ai_delta_graph
Revises: 20260622_0029_evidence_locator
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260623_0030_ai_delta_graph"
down_revision = "20260622_0029_evidence_locator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable graph, node, call, checkpoint, result, and outbox tables."""
    op.create_table(
        "ai_graph_runs",
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("context_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("context_input_hash", sa.String(length=96), nullable=False),
        sa.Column("identity_hash", sa.String(length=96), nullable=False),
        sa.Column("state_hash", sa.String(length=96), nullable=False),
        sa.Column("scope_version_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("review_mode", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("effective_assessment_id", sa.String(length=64), nullable=True),
        sa.Column(
            "llm_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tool_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "retrieval_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "repair_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("graph_run_id"),
    )
    op.create_index(
        "ix_ai_graph_runs_security_decision",
        "ai_graph_runs",
        ["security_id", "decision_at"],
    )
    op.create_index(
        "ix_ai_graph_runs_context",
        "ai_graph_runs",
        ["context_snapshot_id"],
    )

    op.create_table(
        "ai_graph_node_runs",
        sa.Column("node_run_id", sa.String(length=64), nullable=False),
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=96), nullable=False),
        sa.Column("output_hash", sa.String(length=96), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("tool_policy_version", sa.String(length=64), nullable=True),
        sa.Column(
            "error_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("node_run_id"),
        sa.UniqueConstraint(
            "graph_run_id",
            "node_name",
            "attempt_no",
            name="uq_ai_graph_node_attempt",
        ),
    )
    op.create_index(
        "ix_ai_graph_node_runs_graph_node",
        "ai_graph_node_runs",
        ["graph_run_id", "node_name"],
    )

    op.create_table(
        "ai_graph_checkpoints",
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=96), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=96), nullable=True),
        sa.Column("identity_hash", sa.String(length=96), nullable=False),
        sa.Column("state_hash", sa.String(length=96), nullable=False),
        sa.Column(
            "state_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "checkpoint_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("graph_run_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_index(
        "ix_ai_graph_checkpoints_created",
        "ai_graph_checkpoints",
        ["graph_run_id", "created_at"],
    )

    op.create_table(
        "tool_call_records",
        sa.Column("tool_call_id", sa.String(length=64), nullable=False),
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("tool_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("request_hash", sa.String(length=96), nullable=False),
        sa.Column("response_hash", sa.String(length=96), nullable=True),
        sa.Column(
            "request_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tool_call_id"),
    )
    op.create_index(
        "ix_tool_call_records_graph_node",
        "tool_call_records",
        ["graph_run_id", "node_name"],
    )

    op.create_table(
        "llm_call_records",
        sa.Column("llm_call_id", sa.String(length=64), nullable=False),
        sa.Column("billing_key", sa.String(length=128), nullable=False),
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=96), nullable=False),
        sa.Column("schema_hash", sa.String(length=96), nullable=False),
        sa.Column("request_hash", sa.String(length=96), nullable=False),
        sa.Column("response_hash", sa.String(length=96), nullable=True),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "request_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("llm_call_id"),
        sa.UniqueConstraint(
            "billing_key",
            name="uq_llm_call_billing_key",
        ),
    )
    op.create_index(
        "ix_llm_call_records_graph_node",
        "llm_call_records",
        ["graph_run_id", "node_name"],
    )

    op.create_table(
        "research_delta_reviews",
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("context_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_mode", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "previous_effective_assessment_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("effective_assessment_id", sa.String(length=64), nullable=True),
        sa.Column("assessment_freshness", sa.String(length=32), nullable=True),
        sa.Column("stale_reason", sa.String(length=128), nullable=True),
        sa.Column(
            "changed_assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "model_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "prompt_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tool_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "llm_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tool_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("result_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("review_id"),
        sa.UniqueConstraint(
            "graph_run_id",
            name="uq_research_delta_review_graph_run",
        ),
    )
    op.create_index(
        "ix_research_delta_reviews_security_decision",
        "research_delta_reviews",
        ["security_id", "decision_at"],
    )

    op.create_table(
        "research_delta_outbox",
        sa.Column("outbox_id", sa.String(length=64), nullable=False),
        sa.Column("graph_run_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_run_id"],
            ["ai_graph_runs.graph_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("outbox_id"),
        sa.UniqueConstraint(
            "graph_run_id",
            "event_type",
            name="uq_research_delta_outbox_event",
        ),
    )
    op.create_index(
        "ix_research_delta_outbox_status_next",
        "research_delta_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    """Drop the v0.2 AI delta review graph schema."""
    op.drop_index(
        "ix_research_delta_outbox_status_next",
        table_name="research_delta_outbox",
    )
    op.drop_table("research_delta_outbox")
    op.drop_index(
        "ix_research_delta_reviews_security_decision",
        table_name="research_delta_reviews",
    )
    op.drop_table("research_delta_reviews")
    op.drop_index("ix_llm_call_records_graph_node", table_name="llm_call_records")
    op.drop_table("llm_call_records")
    op.drop_index("ix_tool_call_records_graph_node", table_name="tool_call_records")
    op.drop_table("tool_call_records")
    op.drop_index(
        "ix_ai_graph_checkpoints_created",
        table_name="ai_graph_checkpoints",
    )
    op.drop_table("ai_graph_checkpoints")
    op.drop_index(
        "ix_ai_graph_node_runs_graph_node",
        table_name="ai_graph_node_runs",
    )
    op.drop_table("ai_graph_node_runs")
    op.drop_index("ix_ai_graph_runs_context", table_name="ai_graph_runs")
    op.drop_index(
        "ix_ai_graph_runs_security_decision",
        table_name="ai_graph_runs",
    )
    op.drop_table("ai_graph_runs")
