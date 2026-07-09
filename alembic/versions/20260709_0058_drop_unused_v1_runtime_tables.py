"""Drop unused v1 draft runtime tables.

Revision ID: 20260709_0058_runtime_cleanup
Revises: 20260708_0057_v1_runtime
Create Date: 2026-07-09 10:30:00
"""

from __future__ import annotations

from alembic import op

revision = "20260709_0058_runtime_cleanup"
down_revision = "20260708_0057_v1_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove unintegrated draft runtime tables from the database head."""
    op.drop_table("data_freshness_states", schema="ops")
    op.drop_table("system_health_snapshots", schema="ops")
    op.drop_table("backfill_quality_reports", schema="ops")
    op.drop_table("backfill_partitions", schema="ops")
    op.drop_table("backfill_campaigns", schema="ops")

    op.drop_table("llm_call_audits", schema="prompt")
    op.drop_table("prompt_render_history", schema="prompt")
    op.drop_table("prompt_bundles", schema="prompt")
    op.drop_table("prompt_templates", schema="prompt")

    op.drop_table("tool_rate_limit_buckets", schema="tool")
    op.drop_table("tool_catalog_versions", schema="tool")
    op.drop_table("tool_results", schema="tool")
    op.drop_table("tool_calls", schema="tool")

    op.drop_table("audit_reports", schema="agent")
    op.drop_table("context_omissions", schema="agent")
    op.drop_table("domain_context_capsules", schema="agent")
    op.drop_table("context_facts", schema="agent")
    op.drop_table("context_packs", schema="agent")
    op.drop_table("artifacts", schema="agent")
    op.drop_table("task_events", schema="agent")
    op.drop_table("worker_tasks", schema="agent")
    op.drop_table("domain_tasks", schema="agent")
    op.drop_table("runs", schema="agent")

    op.drop_table("dead_letter_queue", schema="platform")
    op.drop_table("outbox_events", schema="platform")
    op.drop_table("config_resolution_snapshots", schema="platform")
    op.drop_table("runtime_environments", schema="platform")
    op.drop_table("idempotency_keys", schema="platform")


def downgrade() -> None:
    """Keep the cleanup irreversible because the dropped tables were unused drafts."""
    raise NotImplementedError(
        "The removed v1 draft runtime tables were not used by application code. "
        "Restore from revision 20260708_0057_v1_runtime if those draft tables are needed."
    )
