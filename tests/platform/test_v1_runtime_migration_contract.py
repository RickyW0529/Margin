"""test_v1_runtime_migration_contract module."""

from __future__ import annotations

from pathlib import Path

VERSIONS_DIR = Path("alembic/versions")

UNUSED_V1_RUNTIME_TABLES = (
    ("platform", "idempotency_keys"),
    ("platform", "runtime_environments"),
    ("platform", "config_resolution_snapshots"),
    ("platform", "outbox_events"),
    ("platform", "dead_letter_queue"),
    ("agent", "runs"),
    ("agent", "domain_tasks"),
    ("agent", "worker_tasks"),
    ("agent", "task_events"),
    ("agent", "artifacts"),
    ("agent", "context_packs"),
    ("agent", "context_facts"),
    ("agent", "domain_context_capsules"),
    ("agent", "context_omissions"),
    ("agent", "audit_reports"),
    ("tool", "tool_calls"),
    ("tool", "tool_results"),
    ("tool", "tool_catalog_versions"),
    ("tool", "tool_rate_limit_buckets"),
    ("prompt", "prompt_templates"),
    ("prompt", "prompt_bundles"),
    ("prompt", "prompt_render_history"),
    ("prompt", "llm_call_audits"),
    ("ops", "backfill_campaigns"),
    ("ops", "backfill_partitions"),
    ("ops", "backfill_quality_reports"),
    ("ops", "system_health_snapshots"),
    ("ops", "data_freshness_states"),
)


def test_agent_tool_prompt_platform_runtime_tables_are_declared() -> None:
    """test_agent_tool_prompt_platform_runtime_tables_are_declared implementation.

    Returns:
        None: .
    """
    migration = VERSIONS_DIR.joinpath(
        "20260708_0057_agent_tool_prompt_platform_runtime.py"
    ).read_text(encoding="utf-8")

    for required in (
        "agent.runs",
        "agent.domain_tasks",
        "agent.worker_tasks",
        "agent.task_events",
        "agent.artifacts",
        "agent.context_packs",
        "agent.context_facts",
        "agent.domain_context_capsules",
        "tool.tool_calls",
        "tool.tool_results",
        "prompt.prompt_templates",
        "prompt.prompt_bundles",
        "prompt.prompt_render_history",
        "platform.idempotency_keys",
        "platform.outbox_events",
        "platform.dead_letter_queue",
        "ops.backfill_campaigns",
        "ops.backfill_partitions",
        "ops.backfill_quality_reports",
        "ops.system_health_snapshots",
        "ops.data_freshness_states",
    ):
        assert required in migration


def test_runtime_cleanup_migration_is_final_v1_head() -> None:
    """test_runtime_cleanup_migration_is_final_v1_head implementation.

    Returns:
        None: .
    """
    runtime_migration = VERSIONS_DIR.joinpath(
        "20260708_0057_agent_tool_prompt_platform_runtime.py"
    ).read_text(encoding="utf-8")
    cleanup_migration = VERSIONS_DIR.joinpath(
        "20260709_0058_drop_unused_v1_runtime_tables.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260708_0056_mart_app"' in runtime_migration
    assert 'revision = "20260708_0057_v1_runtime"' in runtime_migration
    assert 'down_revision = "20260708_0057_v1_runtime"' in cleanup_migration
    assert 'revision = "20260709_0058_runtime_cleanup"' in cleanup_migration


def test_unused_v1_runtime_tables_are_removed_by_cleanup_migration() -> None:
    """Ensure unintegrated v1 draft runtime tables do not remain at the head.

    Returns:
        None: .
    """
    migration = VERSIONS_DIR.joinpath(
        "20260709_0058_drop_unused_v1_runtime_tables.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260708_0057_v1_runtime"' in migration
    for schema, table_name in UNUSED_V1_RUNTIME_TABLES:
        assert f'op.drop_table("{table_name}", schema="{schema}")' in migration


def test_formal_platform_ops_runtime_tables_are_reintroduced_after_cleanup() -> None:
    """Formal platform and ops runtime tables should be reintroduced after cleanup."""
    migration = VERSIONS_DIR.joinpath(
        "20260709_0063_platform_ops_runtime.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260709_0062_prompts"' in migration
    for required in (
        "platform.idempotency_keys",
        "platform.runtime_environments",
        "platform.config_resolution_snapshots",
        "platform.outbox_events",
        "platform.dead_letter_queue",
        "ops.backfill_campaigns",
        "ops.backfill_partitions",
        "ops.backfill_quality_reports",
        "ops.system_health_snapshots",
        "ops.data_freshness_states",
    ):
        assert required in migration
