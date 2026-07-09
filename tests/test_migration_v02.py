"""Migration verifier tests for deployment audit schema.

Verifies that the full Alembic migration sequence runs cleanly from an empty
database and produces the expected current schema head and table set.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

from scripts.verify_migrations import verify_clean_database


def test_migration_sequence_from_clean_database(database_url: str) -> None:
    """Test that the full migration sequence runs from a clean database.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    url = make_url(database_url)
    clean_database_name = f"{url.database}_migration_v02"

    result = verify_clean_database(
        database_url,
        database_name=clean_database_name,
        drop_existing=True,
    )

    assert result.current_head == result.expected_head
    assert result.current_head == "20260708_0052_runtime_config"
    assert result.failed_revision is None
    assert {
        "orchestration_runs",
        "orchestration_step_attempts",
        "transactional_outbox",
        "capacity_limit_versions",
        "quant_input_snapshots",
        "quant_screen_results",
        "effective_assessment_pointers",
        "news_refresh_runs",
        "news_refresh_targets",
        "document_security_links",
        "document_materiality_scores",
        "news_context_bundles",
        "news_context_documents",
        "indexed_documents",
        "chunk_security_links",
        "evidence_packages",
        "evidence_package_items",
        "claim_evidence_links",
        "evidence_conflicts",
        "news_context_evidence",
        "ai_graph_runs",
        "ai_graph_node_runs",
        "ai_graph_checkpoints",
        "tool_call_records",
        "llm_call_records",
        "research_delta_reviews",
        "research_delta_outbox",
        "data_acquisition_policy_versions",
        "quant_data_requirements",
        "provider_endpoint_requirements",
        "provider_endpoint_requirement_links",
        "source_quality_decisions",
        "source_akshare.ak_stock_zh_a_spot_em",
        "source_akshare.ak_stock_zh_a_hist",
        "source_akshare.ak_stock_balance_sheet_by_report_em",
        "source_akshare.ak_stock_value_em",
        "source_akshare.ak_index_stock_cons_csindex",
        "company_pool_snapshots",
        "company_pool_members",
        "analysis_snapshots",
        "analysis_metrics",
        "analysis_findings",
        "analysis_evidence_links",
        "quant_feature_snapshots",
        "quant_feature_rows",
        "news_agent_runs",
        "news_agent_tasks",
        "news_search_plans",
        "news_article_findings",
        "news_security_briefs",
        "agent_runtime_runs",
        "agent_runtime_steps",
        "agent_runtime_artifacts",
        "agent_runtime_guardrail_decisions",
        "agent_runtime_schedules",
        "agent_chat_sessions",
        "agent_chat_messages",
        "agent_flow_versions",
        "quant_agent_profile_versions",
        "config_resolution_snapshots",
        "config_resolution_snapshot_entries",
        "dashboard_runs",
        "dashboard_items",
        "source_tushare.ts_moneyflow",
        "source_tushare.ts_margin_detail",
        "source_tushare.ts_forecast",
        "source_tushare.ts_express",
        "source_tushare.ts_limit_list_d",
    } <= set(result.tables)
    assert {
        "portfolios",
        "trades",
        "position_theses",
        "alert_events",
        "position_reviews",
        "indicator_definitions",
        "provider_indicator_mappings",
        "universe_definitions",
        "universe_versions",
        "universe_snapshots",
        "universe_memberships",
        "research_refresh_events",
        "valuation_refresh_runs",
        "valuation_refresh_steps",
        "confidence_components",
        "idempotency_records",
        "smoke_run_records",
    }.isdisjoint(result.tables)
    assert result.pgvector_available is True
