"""test_v1_runtime_migration_contract module."""

from __future__ import annotations

from pathlib import Path


def test_agent_tool_prompt_platform_runtime_tables_are_declared() -> None:
    """test_agent_tool_prompt_platform_runtime_tables_are_declared implementation.

    Returns:
        None: .
    """
    migration = Path(
        "alembic/versions/20260708_0057_agent_tool_prompt_platform_runtime.py"
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


def test_runtime_migration_is_final_v1_head() -> None:
    """test_runtime_migration_is_final_v1_head implementation.

    Returns:
        None: .
    """
    migration = Path(
        "alembic/versions/20260708_0057_agent_tool_prompt_platform_runtime.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260708_0056_mart_app"' in migration
    assert 'revision = "20260708_0057_v1_runtime"' in migration
