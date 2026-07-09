"""Add v1 agent, tool, prompt, platform, and ops runtime tables.

Revision ID: 20260708_0057_agent_tool_prompt_platform_runtime
Revises: 20260708_0056_kimball_mart_app_tables
Create Date: 2026-07-09 00:15:00
"""

from __future__ import annotations

# ruff: noqa: E501
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260708_0057_v1_runtime"
down_revision = "20260708_0056_mart_app"
branch_labels = None
depends_on = None

# Contract anchors:
# agent.runs
# agent.domain_tasks
# agent.worker_tasks
# agent.task_events
# agent.artifacts
# agent.context_packs
# agent.context_facts
# agent.domain_context_capsules
# tool.tool_calls
# tool.tool_results
# prompt.prompt_templates
# prompt.prompt_bundles
# prompt.prompt_render_history
# platform.idempotency_keys
# platform.outbox_events
# platform.dead_letter_queue
# ops.backfill_campaigns
# ops.backfill_partitions
# ops.backfill_quality_reports
# ops.system_health_snapshots
# ops.data_freshness_states


def _jsonb() -> postgresql.JSONB:
    """Process _jsonb.

    Returns:
        postgresql.JSONB: Return value.
    """
    return postgresql.JSONB(astext_type=sa.Text())


def _text_array() -> postgresql.ARRAY:
    """Process _text_array.

    Returns:
        postgresql.ARRAY: Return value.
    """
    return postgresql.ARRAY(sa.Text())


def upgrade() -> None:
    """Create v1 platform runtime tables."""
    _create_platform_tables()
    _create_agent_tables()
    _create_tool_tables()
    _create_prompt_tables()
    _create_ops_tables()


def _create_platform_tables() -> None:
    # platform.idempotency_keys
    """Process _create_platform_tables.

    Returns:
        None: Return value.
    """
    op.create_table(
        "idempotency_keys",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_hash", sa.Text()),
        sa.Column("response_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="platform",
    )
    op.create_table(
        "config_resolution_snapshots",
        sa.Column("config_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text()),
        sa.Column("environment_id", sa.Text()),
        sa.Column("resolved_config_json", _jsonb(), nullable=False),
        sa.Column("resolved_config_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="platform",
    )
    # platform.outbox_events
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        schema="platform",
    )
    # platform.dead_letter_queue
    op.create_table(
        "dead_letter_queue",
        sa.Column("dlq_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("payload_redacted_json", _jsonb()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="platform",
    )


def _create_agent_tables() -> None:
    # agent.runs
    """Process _create_agent_tables.

    Returns:
        None: Return value.
    """
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text()),
        sa.Column("chat_session_id", sa.Text()),
        sa.Column("root_idempotency_key", sa.Text()),
        sa.Column("config_snapshot_id", sa.Text()),
        sa.Column("tool_catalog_version_id", sa.Text()),
        sa.Column("prompt_bundle_refs", _jsonb()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("metadata_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="agent",
    )
    # agent.domain_tasks
    op.create_table(
        "domain_tasks",
        sa.Column("domain_task_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("agent.runs.run_id"), nullable=False),
        sa.Column("expert_agent", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("required_output_artifact_types", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("input_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("capability_token_id", sa.Text()),
        sa.Column("context_pack_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("metadata_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="agent",
    )
    # agent.worker_tasks
    op.create_table(
        "worker_tasks",
        sa.Column("worker_task_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("agent.runs.run_id"), nullable=False),
        sa.Column("domain_task_id", sa.Text(), sa.ForeignKey("agent.domain_tasks.domain_task_id"), nullable=False),
        sa.Column("worker_agent", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("required_output_artifact_types", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("input_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("tool_allowlist", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("capability_token_id", sa.Text()),
        sa.Column("context_pack_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("metadata_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="agent",
    )
    # agent.task_events
    op.create_table(
        "task_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("task_level", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="agent",
    )
    # agent.artifacts
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("agent.runs.run_id"), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("artifact_schema_version", sa.Text(), nullable=False),
        sa.Column("producer_agent", sa.Text(), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("source_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("evidence_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="safe"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("artifact_id", "payload_hash", name="uq_agent_artifacts_hash"),
        schema="agent",
    )
    op.create_table(
        "context_packs",
        sa.Column("context_pack_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("created_for_agent", sa.Text(), nullable=False),
        sa.Column("user_goal", sa.Text(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("policy_snapshot_ref", sa.Text()),
        sa.Column("pack_json", _jsonb(), nullable=False),
        sa.Column("pack_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="agent",
    )
    op.create_table(
        "context_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("context_pack_id", sa.Text(), sa.ForeignKey("agent.context_packs.context_pack_id"), nullable=False),
        sa.Column("fact_type", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("value_json", _jsonb()),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("source_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("evidence_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        schema="agent",
    )
    op.create_table(
        "domain_context_capsules",
        sa.Column("capsule_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("domain_task_id", sa.Text(), nullable=False),
        sa.Column("expert_agent", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("capsule_json", _jsonb(), nullable=False),
        sa.Column("capsule_hash", sa.Text(), nullable=False),
        sa.Column("output_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("audit_report_ref", sa.Text()),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="agent",
    )
    op.create_table(
        "context_omissions",
        sa.Column("omission_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("context_pack_id", sa.Text(), sa.ForeignKey("agent.context_packs.context_pack_id"), nullable=False),
        sa.Column("omitted_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="agent",
    )
    op.create_table(
        "audit_reports",
        sa.Column("audit_report_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("audit_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("rejected_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("blocking_reasons", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("audit_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="agent",
    )


def _create_tool_tables() -> None:
    # tool.tool_calls
    """Process _create_tool_tables.

    Returns:
        None: Return value.
    """
    op.create_table(
        "tool_calls",
        sa.Column("tool_call_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("caller_agent", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("input_redacted_json", _jsonb(), nullable=False),
        sa.Column("capability_token_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tool",
    )
    # tool.tool_results
    op.create_table(
        "tool_results",
        sa.Column("tool_call_id", sa.Text(), sa.ForeignKey("tool.tool_calls.tool_call_id"), primary_key=True),
        sa.Column("output_hash", sa.Text()),
        sa.Column("output_redacted_json", _jsonb()),
        sa.Column("output_artifact_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("output_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="tool",
    )
    op.create_table(
        "tool_catalog_versions",
        sa.Column("tool_catalog_version_id", sa.Text(), primary_key=True),
        sa.Column("catalog_json", _jsonb(), nullable=False),
        sa.Column("catalog_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tool",
    )
    op.create_table(
        "tool_rate_limit_buckets",
        sa.Column("bucket_id", sa.Text(), primary_key=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        schema="tool",
    )


def _create_prompt_tables() -> None:
    # prompt.prompt_templates
    """Process _create_prompt_tables.

    Returns:
        None: Return value.
    """
    op.create_table(
        "prompt_templates",
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("allowed_variables", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("output_schema_ref", sa.Text()),
        sa.Column("safety_tags", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("prompt_id", "version"),
        schema="prompt",
    )
    # prompt.prompt_bundles
    op.create_table(
        "prompt_bundles",
        sa.Column("prompt_bundle_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("target_agent_type", sa.Text(), nullable=False),
        sa.Column("template_refs", _jsonb(), nullable=False),
        sa.Column("model_profile_ref", sa.Text()),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="prompt",
    )
    # prompt.prompt_render_history
    op.create_table(
        "prompt_render_history",
        sa.Column("render_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("prompt_bundle_id", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("variables_hash", sa.Text(), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="prompt",
    )
    op.create_table(
        "llm_call_audits",
        sa.Column("llm_call_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_render_id", sa.Text(), nullable=False),
        sa.Column("input_token_count", sa.Integer()),
        sa.Column("output_token_count", sa.Integer()),
        sa.Column("temperature", sa.Numeric(4, 3)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        schema="prompt",
    )


def _create_ops_tables() -> None:
    # ops.backfill_campaigns
    """Process _create_ops_tables.

    Returns:
        None: Return value.
    """
    op.create_table(
        "backfill_campaigns",
        sa.Column("campaign_id", sa.Text(), primary_key=True),
        sa.Column("campaign_name", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("providers", _text_array(), nullable=False),
        sa.Column("endpoint_plan_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("created_by_run_id", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    # ops.backfill_partitions
    op.create_table(
        "backfill_partitions",
        sa.Column("partition_id", sa.Text(), primary_key=True),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("ops.backfill_campaigns.campaign_id"), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("endpoint_name", sa.Text(), nullable=False),
        sa.Column("partition_start", sa.Date(), nullable=False),
        sa.Column("partition_end", sa.Date(), nullable=False),
        sa.Column("params_json", _jsonb(), nullable=False),
        sa.Column("params_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("raw_snapshot_refs", _text_array(), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("quality_report_ref", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("campaign_id", "provider_name", "endpoint_name", "params_hash", name="uq_backfill_partitions_params"),
        schema="ops",
    )
    # ops.backfill_quality_reports
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
        sa.Column("missing_dates", postgresql.ARRAY(sa.Date()), nullable=False, server_default=sa.text("ARRAY[]::DATE[]")),
        sa.Column("duplicate_key_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_drift_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("report_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    # ops.system_health_snapshots
    op.create_table(
        "system_health_snapshots",
        sa.Column("health_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("component_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("metrics_json", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    # ops.data_freshness_states
    op.create_table(
        "data_freshness_states",
        sa.Column("freshness_state_id", sa.Text(), primary_key=True),
        sa.Column("dataset_name", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text()),
        sa.Column("latest_available_date", sa.Date()),
        sa.Column("latest_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("stale_after", sa.Interval()),
        sa.Column("freshness_status", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )


def downgrade() -> None:
    """Drop only tables introduced by this revision."""
    for schema, table in (
        ("ops", "data_freshness_states"),
        ("ops", "system_health_snapshots"),
        ("ops", "backfill_quality_reports"),
        ("ops", "backfill_partitions"),
        ("ops", "backfill_campaigns"),
        ("prompt", "llm_call_audits"),
        ("prompt", "prompt_render_history"),
        ("prompt", "prompt_bundles"),
        ("prompt", "prompt_templates"),
        ("tool", "tool_rate_limit_buckets"),
        ("tool", "tool_catalog_versions"),
        ("tool", "tool_results"),
        ("tool", "tool_calls"),
        ("agent", "audit_reports"),
        ("agent", "context_omissions"),
        ("agent", "domain_context_capsules"),
        ("agent", "context_facts"),
        ("agent", "context_packs"),
        ("agent", "artifacts"),
        ("agent", "task_events"),
        ("agent", "worker_tasks"),
        ("agent", "domain_tasks"),
        ("agent", "runs"),
        ("platform", "dead_letter_queue"),
        ("platform", "outbox_events"),
        ("platform", "config_resolution_snapshots"),
        ("platform", "runtime_environments"),
        ("platform", "idempotency_keys"),
    ):
        op.drop_table(table, schema=schema)
