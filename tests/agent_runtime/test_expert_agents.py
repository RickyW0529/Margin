"""Tests for ExpertAgent executors."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agent_runtime.expert_agents import (
    DataAnalystAgent,
    GeneralQnaAgent,
    StockAnalystAgent,
)
from margin.agent_runtime.models import AgentExecutionStatus
from margin.dashboard.models import DashboardFilters, DashboardSort, ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import DeterministicLLMProvider


def test_data_analyst_agent_writes_analysis_and_answer_artifacts() -> None:
    """DataAnalystAgent produces the user answer and Context Store artifacts."""
    context_store = MemoryAgentContextStore()
    repository = MemoryDashboardRepository()
    services = DashboardServiceBundle.in_memory(dashboard_repository=repository)
    run = ResearchRun(
        run_id="run-1",
        decision_at=datetime(2026, 7, 8, tzinfo=UTC),
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ"],
        status="partial",
        item_count=1,
        published_count=1,
    )
    repository.add_run(run)
    repository.add_items(
        [
            ResearchItem(
                item_id="item-1",
                run_id=run.run_id,
                symbol="000001.SZ",
                signal_type="research_candidate",
                confidence=0.82,
                statement="经营现金流改善",
                workflow_run_id="wf-1",
                snapshot_id="snapshot-1",
                status="published",
            )
        ]
    )

    provider = DeterministicLLMProvider(
        response={"content": "LLM 基于当前数据回答：000001.SZ。"}
    )
    result = DataAnalystAgent(
        llm_provider=provider,
        write_context_artifact=context_store.add_artifact,
    ).answer_recommendation_question(
        run_id="ar_qna_1",
        message="今日推荐股票是什么？",
        scope_version_id="scope-1",
        universe="ALL_A",
        language="zh",
        services=services,
    )

    assert result.status == AgentExecutionStatus.SUCCEEDED
    assert result.answer == "LLM 基于当前数据回答：000001.SZ。"
    assert "000001.SZ" in result.answer
    assert [artifact.artifact_type for artifact in result.artifacts] == [
        "analysis_table",
        "explanation",
    ]
    explanation = context_store.get_artifact("ctx_ar_qna_1_explanation")
    assert explanation is not None
    assert explanation.payload_json["answer"] == result.answer
    assert explanation.payload_json["producer_prompt_id"] == (
        "data_analyst_qna_agent_v0.4"
    )


def test_general_qna_agent_calls_llm_and_writes_explanation_artifact() -> None:
    """GeneralQnaAgent answers greetings through the configured LLM provider."""
    context_store = MemoryAgentContextStore()
    provider = DeterministicLLMProvider(response={"content": "你好，我是 Margin。"})

    result = GeneralQnaAgent(
        llm_provider=provider,
        write_context_artifact=context_store.add_artifact,
    ).answer_general_question(
        run_id="ar_qna_greeting",
        message="你好",
        language="zh",
        available_artifacts=(),
    )

    assert result.status == AgentExecutionStatus.SUCCEEDED
    assert result.answer == "你好，我是 Margin。"
    assert [artifact.artifact_type for artifact in result.artifacts] == [
        "explanation",
    ]
    explanation = context_store.get_artifact("ctx_ar_qna_greeting_explanation")
    assert explanation is not None
    assert explanation.producer_agent == "GeneralQnaAgent"
    assert explanation.payload_json["answer"] == result.answer
    assert explanation.payload_json["prompt_hash"].startswith("sha256:")


def test_stock_analyst_agent_writes_portfolio_adjustment_artifact() -> None:
    """StockAnalystAgent can remove risky quant candidates and persist adjustments."""
    context_store = MemoryAgentContextStore()

    result = StockAnalystAgent(
        write_context_artifact=context_store.add_artifact,
    ).adjust_quant_candidates(
        run_id="ar_sched_1",
        candidates=(
            {
                "security_id": "keep.SZ",
                "target_weight": 0.50,
                "screening_status": "pass",
                "review_required": False,
                "risk_flags": [],
            },
            {
                "security_id": "delete.SZ",
                "target_weight": 0.30,
                "screening_status": "pass",
                "review_required": True,
                "risk_flags": ["short_term_overheat"],
            },
        ),
        max_stock_exposure=0.80,
    )

    assert result.status == AgentExecutionStatus.SUCCEEDED
    assert result.removed_security_ids == ("delete.SZ",)
    assert result.adjustments[0]["security_id"] == "keep.SZ"
    assert result.adjustments[0]["adjusted_weight"] == 0.50
    assert result.adjustments[1]["action"] == "delete"
    assert result.adjustments[1]["adjusted_weight"] == 0.0
    artifact = context_store.get_artifact("ctx_ar_sched_1_portfolio_adjustment")
    assert artifact is not None
    assert artifact.artifact_type == "portfolio_adjustment"
    assert artifact.producer_agent == "StockAnalystAgent"
    assert artifact.payload_json["removed_security_ids"] == ["delete.SZ"]
    assert artifact.payload_json["max_stock_exposure"] == 0.80


def test_stock_analyst_agent_publishes_adjusted_dashboard_projection() -> None:
    """StockAnalystAgent makes adjusted weights visible to dashboard/Q&A readers."""
    context_store = MemoryAgentContextStore()
    repository = MemoryDashboardRepository()
    source_run = ResearchRun(
        run_id="dr_quant_1",
        decision_at=datetime(2026, 7, 8, tzinfo=UTC),
        strategy_id="quant_run_1",
        version_id="scope-1",
        universe=["keep.SZ", "reduce.SZ", "delete.SZ"],
        status="published",
        item_count=3,
        published_count=3,
    )
    source_items = [
        ResearchItem(
            item_id="di_keep",
            run_id=source_run.run_id,
            symbol="keep.SZ",
            confidence=0.90,
            statement="keep",
            status="published",
            target_weight=0.50,
            adjusted_weight=0.50,
        ),
        ResearchItem(
            item_id="di_reduce",
            run_id=source_run.run_id,
            symbol="reduce.SZ",
            confidence=0.80,
            statement="reduce",
            status="published",
            target_weight=0.50,
            adjusted_weight=0.50,
        ),
        ResearchItem(
            item_id="di_delete",
            run_id=source_run.run_id,
            symbol="delete.SZ",
            confidence=0.70,
            statement="delete",
            status="published",
            target_weight=0.20,
            adjusted_weight=0.20,
        ),
    ]
    repository.add_run(source_run)
    repository.add_items(source_items)

    result = StockAnalystAgent(
        write_context_artifact=context_store.add_artifact,
        dashboard_repository=repository,
    ).adjust_quant_candidates(
        run_id="ar_sched_1",
        candidates=(
            {
                "item_id": "di_keep",
                "security_id": "keep.SZ",
                "target_weight": 0.50,
                "screening_status": "pass",
            },
            {
                "item_id": "di_reduce",
                "security_id": "reduce.SZ",
                "target_weight": 0.50,
                "screening_status": "pass",
            },
            {
                "item_id": "di_delete",
                "security_id": "delete.SZ",
                "target_weight": 0.20,
                "screening_status": "pass",
                "risk_flags": ["short_term_overheat"],
            },
        ),
        max_stock_exposure=0.80,
    )

    assert result.dashboard_run_id == "dr_agent_ar_sched_1"
    latest = repository.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="symbol", direction="asc"),
        cursor=None,
        limit=10,
    )
    assert [item.security_id for item in latest.items] == ["keep.SZ", "reduce.SZ"]
    assert sum(item.adjusted_weight or 0.0 for item in latest.items) == 0.80
    assert latest.items[0].agent_adjustment["source"] == "StockAnalystAgent"
    assert latest.items[0].agent_adjustment["action"] == "reduce_weight"
    assert latest.items[1].agent_adjustment["action"] == "reduce_weight"
    artifact = context_store.get_artifact("ctx_ar_sched_1_portfolio_adjustment")
    assert artifact is not None
    assert artifact.payload_json["dashboard_run_id"] == "dr_agent_ar_sched_1"
    projection_event = context_store.get_artifact(
        "ctx_ar_sched_1_dashboard_projection_event"
    )
    assert projection_event is not None
    assert projection_event.artifact_type == "dashboard_projection_event"
    assert projection_event.payload_json["dashboard_run_id"] == "dr_agent_ar_sched_1"
