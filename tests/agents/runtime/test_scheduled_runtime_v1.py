"""Contracts for the v1 scheduled Agent runtime."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agent_runtime.schedules import StockAnalysisSchedule
from margin.agents.runtime.scheduled import ScheduledAgentRuntimeRunner
from margin.research.llm import DeterministicLLMProvider


def test_v1_scheduled_runner_starts_refresh_and_writes_v1_artifacts() -> None:
    """Due schedules should run without the legacy MainAgent runtime."""
    context_store = MemoryAgentContextStore()
    valuation_service = _FakeValuationService()
    repository = _DueScheduleRepository(
        StockAnalysisSchedule(
            enabled=True,
            hour=8,
            minute=30,
            timezone="Asia/Shanghai",
            scope_version_id="scope-current",
            universe="ALL_A",
            next_run_at=datetime(2026, 7, 7, 0, 30, tzinfo=UTC),
        )
    )

    processed = ScheduledAgentRuntimeRunner(
        repository=repository,
        context_store=context_store,
        valuation_service=valuation_service,
        scope_resolver=lambda scope: "scope-1" if scope == "scope-current" else scope,
        llm_provider_factory=_scheduled_planner_factory,
    ).run_once(now=datetime(2026, 7, 7, 0, 31, tzinfo=UTC))

    assert processed == 1
    assert len(valuation_service.calls) == 1
    scope_version_id, decision_at, idempotency_key, metadata = valuation_service.calls[0]
    assert scope_version_id == "scope-1"
    assert decision_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)
    assert idempotency_key == "stock_analysis_daily:2026-07-07"
    assert metadata["agent_runtime_version"] == "scheduled-agent-runtime-v1"
    assert metadata["global_plan"]["created_by"] == "MainAgent"
    assert metadata["global_plan"]["domain_task_count"] >= 3
    assert metadata["scheduled_task_intent"]["planner"] == "MainAgent"
    assert metadata["main_agent_plan"]["planning_mode"] == "prompt_dynamic"
    assert metadata["main_agent_plan"]["planning_prompt_ref"] == "main_agent_scheduled_planner_v1"
    assert metadata["plan_validation"]["valid"] is True
    assert "QuantExpertAgent" in metadata["main_agent_plan"]["domain_agents"]
    assert "StockResearchExpertAgent" in metadata["main_agent_plan"]["domain_agents"]

    artifacts = context_store.list_artifacts("ar_sched_20260707_0830")
    assert [artifact.artifact_type for artifact in artifacts] == [
        "scheduled_global_plan",
        "valuation_refresh",
    ]
    assert artifacts[0].producer_agent == "MainAgent"
    assert artifacts[1].producer_agent == "QuantExpertAgent"
    assert artifacts[1].payload_json["valuation_refresh_run_id"] == "refresh-1"
    assert repository.saved.last_triggered_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)


def test_worker_uses_v1_scheduled_runner_not_legacy_main_runtime() -> None:
    """Worker scheduling should not construct the legacy MainAgent runtime."""
    import margin.worker as worker_module

    source = inspect.getsource(worker_module)

    assert "ScheduledAgentRuntimeRunner" in source
    assert "ScheduledStockAnalysisRunner" not in source
    assert "get_main_agent_runtime" not in source
    scheduled_source = inspect.getsource(ScheduledAgentRuntimeRunner)
    assert "load_scheduled_stock_analysis_flow" not in scheduled_source


def test_api_dependencies_use_v1_dashboard_publisher_worker() -> None:
    """Valuation publishing should not construct legacy ExpertAgent executors."""
    import margin.api.dependencies as dependency_module

    source = inspect.getsource(dependency_module)

    assert "DashboardPublisherWorker" in source
    assert "StockAnalystAgent" not in source


class _DueScheduleRepository:
    """Fake repository returning one due schedule."""

    def __init__(self, schedule: StockAnalysisSchedule) -> None:
        """Initialize with one schedule."""
        self._schedule = schedule
        self.saved = schedule

    def get_stock_analysis_schedule(self) -> StockAnalysisSchedule:
        """Return the configured schedule."""
        return self._schedule

    def save_stock_analysis_schedule(
        self,
        schedule: StockAnalysisSchedule,
    ) -> StockAnalysisSchedule:
        """Capture the saved schedule."""
        self.saved = schedule
        return schedule

    def list_due_stock_analysis_schedules(
        self,
        *,
        now: datetime,
    ) -> list[StockAnalysisSchedule]:
        """Return the schedule when it is due."""
        if self._schedule.next_run_at and self._schedule.next_run_at <= now:
            return [self._schedule]
        return []


class _FakeValuationService:
    """Fake valuation discovery service recording refresh starts."""

    def __init__(self) -> None:
        """Initialize call storage."""
        self.calls: list[tuple[str, datetime, str | None, dict[str, Any]]] = []

    def start_refresh(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Record one refresh call."""
        self.calls.append((scope_version_id, decision_at, idempotency_key, metadata or {}))
        return type("RefreshResponse", (), {"run_id": "refresh-1"})()


def _scheduled_planner_factory() -> DeterministicLLMProvider:
    """Return the structured MainAgent plan used by scheduled tests."""
    return DeterministicLLMProvider(response=_scheduled_main_plan())


def _scheduled_main_plan() -> dict[str, object]:
    """Return a scheduled stock-research plan as if produced by MainAgent."""
    return {
        "steps": [
            {
                "step_id": "data",
                "agent": "DataExpertAgent",
                "task": "Check PIT data readiness for the scheduled research run.",
                "required_output_types": ["data_readiness"],
            },
            {
                "step_id": "quant",
                "agent": "QuantExpertAgent",
                "task": "Run the quant research line from PIT features.",
                "required_output_types": ["quant_result"],
                "depends_on": ["data"],
            },
            {
                "step_id": "evidence",
                "agent": "EvidenceRagExpertAgent",
                "task": "Prepare fundamental evidence coverage for candidates.",
                "required_output_types": ["evidence_package"],
                "depends_on": ["data"],
            },
            {
                "step_id": "stock",
                "agent": "StockResearchExpertAgent",
                "task": "Fuse quant, financial-report, sentiment, and risk context.",
                "required_output_types": ["stock_research_context_capsule"],
                "depends_on": ["quant", "evidence"],
            },
        ],
        "final_answer_requirements": ["use_approved_capsules_only"],
    }
