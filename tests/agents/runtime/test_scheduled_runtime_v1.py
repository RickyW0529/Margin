"""Contracts for the v1 scheduled Agent runtime."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agent_runtime.schedules import StockAnalysisSchedule
from margin.agents.runtime.scheduled import ScheduledAgentRuntimeRunner
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.research.llm import DeterministicLLMProvider

SCHEDULED_RUN_ID = (
    "ar_sched_20260707_0830_c5782f54_20260707T003100000000Z"
)


def test_v1_scheduled_runner_starts_refresh_and_writes_v1_artifacts() -> None:
    """Due schedules should run without the legacy MainAgent runtime."""
    context_store = MemoryAgentContextStore()
    tool_audit_store = InMemoryToolAuditStore()
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
        tool_audit_store=tool_audit_store,
    ).run_once(now=datetime(2026, 7, 7, 0, 31, tzinfo=UTC))

    assert processed == 1
    assert len(valuation_service.calls) == 1
    scope_version_id, decision_at, idempotency_key, metadata = valuation_service.calls[0]
    assert scope_version_id == "scope-1"
    assert decision_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)
    assert idempotency_key == "stock_analysis_daily:2026-07-07"
    assert metadata["agent_runtime_version"] == "scheduled-agent-runtime-v1"
    assert metadata["global_plan"]["created_by"] == "MainAgent"
    assert metadata["global_plan"]["domain_task_count"] >= 1
    assert metadata["scheduled_task_intent"]["planner"] == "MainAgent"
    assert metadata["main_agent_plan"]["planning_mode"] == "prompt_dynamic"
    assert metadata["main_agent_plan"]["planning_prompt_ref"] == "main_agent_scheduled_planner_v1"
    assert metadata["plan_validation"]["valid"] is True
    assert metadata["execution_boundary"] == "a2a_hierarchical_runtime"
    assert metadata["dispatch_protocol"] == "A2A"
    assert metadata["worker_runtime"] == "langgraph"
    assert "data_readiness" in {
        item["artifact_type"] for item in metadata["input_artifacts"]
    }

    artifacts = context_store.list_artifacts(SCHEDULED_RUN_ID)
    artifacts_by_type = {
        artifact.artifact_type: artifact
        for artifact in artifacts
        if artifact.artifact_type != "worker_activity"
    }
    assert {
        "scheduled_global_plan",
        "data_readiness",
        "valuation_refresh",
        "quant_result",
        "domain_context_capsule",
        "domain_audit_report",
        "l3_execution_report",
    }.issubset(artifacts_by_type)
    plan = artifacts_by_type["scheduled_global_plan"]
    assert plan.producer_agent == "MainAgent"
    assert plan.payload_json["scheduled_planner_mode"] == "dynamic_main_agent_planner"
    assert plan.payload_json["execution_boundary"] == "a2a_hierarchical_runtime"
    assert plan.payload_json["dispatch_protocol"] == "A2A"
    assert plan.payload_json["worker_runtime"] == "langgraph"
    assert plan.payload_json["tool_names"] == [
        "schedule.inspect_data",
        "valuation.start_refresh",
    ]
    assert [
        task["to_domain_agent"] for task in plan.payload_json["global_plan"]["domain_tasks"]
    ] == ["DataExpertAgent", "QuantExpertAgent"]
    assert artifacts_by_type["data_readiness"].producer_agent == "DataInspectionWorker"
    refresh = artifacts_by_type["valuation_refresh"]
    assert refresh.producer_agent == "ValuationRefreshWorker"
    assert refresh.payload_json["valuation_refresh_run_id"] == "refresh-1"
    assert refresh.payload_json["worker_layer"] == "L3"

    activities = [artifact for artifact in artifacts if artifact.artifact_type == "worker_activity"]
    assert {activity.producer_agent for activity in activities} == {
        "DataInspectionWorker",
        "ValuationRefreshWorker",
    }
    assert {
        tool_name for activity in activities for tool_name in activity.payload_json["tool_calls"]
    } == {"schedule.inspect_data", "valuation.start_refresh"}

    report = artifacts_by_type["l3_execution_report"]
    assert report.producer_agent == "MainAgent"
    assert report.payload_json["main_agent_review"]["decision"] == "dispatched"
    assert report.payload_json["research_status"] == "refresh_pending"
    assert report.payload_json["a2a_task_ids"] == [
        f"a2a_{SCHEDULED_RUN_ID}_dt_data",
        f"a2a_{SCHEDULED_RUN_ID}_dt_quant",
    ]
    assert {
        (record.tool_name, record.caller_agent) for record in tool_audit_store.records.values()
    } == {
        ("schedule.inspect_data", "DataInspectionWorker"),
        ("valuation.start_refresh", "ValuationRefreshWorker"),
    }
    assert repository.saved.last_triggered_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)


def test_data_failure_skips_dependent_valuation_worker() -> None:
    """A failed data domain task must prevent the dependent write tool call."""
    context_store = MemoryAgentContextStore()
    tool_audit_store = InMemoryToolAuditStore()
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
        scope_resolver=lambda _scope: "",
        llm_provider_factory=_scheduled_planner_factory,
        tool_audit_store=tool_audit_store,
    ).run_once(now=datetime(2026, 7, 7, 0, 31, tzinfo=UTC))

    assert processed == 1
    assert valuation_service.calls == []
    assert {record.tool_name for record in tool_audit_store.records.values()} == {
        "schedule.inspect_data"
    }
    report = context_store.get_artifact(f"ctx_{SCHEDULED_RUN_ID}_l3_execution_report")
    assert report is not None
    assert report.payload_json["main_agent_review"]["decision"] == "blocked"
    assert report.payload_json["main_agent_review"]["missing_domain_task_ids"] == [
        "dt_data",
        "dt_quant",
    ]


def test_worker_uses_v1_scheduled_runner_not_legacy_main_runtime() -> None:
    """Worker scheduling should not construct the legacy MainAgent runtime."""
    import margin.worker as worker_module

    source = inspect.getsource(worker_module)

    assert "ScheduledAgentRuntimeRunner" in source
    assert "ScheduledStockAnalysisRunner" not in source
    assert "get_main_agent_runtime" not in source
    scheduled_source = inspect.getsource(ScheduledAgentRuntimeRunner)
    assert "load_scheduled_stock_analysis_flow" not in scheduled_source
    assert "run_scheduled_l3_pipeline" not in scheduled_source
    assert "_ensure_scheduled_domain_tasks" not in scheduled_source

    import margin.agents.runtime.scheduled_workers as scheduled_workers_module

    worker_source = inspect.getsource(scheduled_workers_module)
    assert "scheduled_domain_agent_cards()" in worker_source
    assert "scheduled_worker_agent_cards()" in worker_source
    assert "DomainAgentCard(" not in worker_source
    assert "WorkerAgentCard(" not in worker_source
    assert "WorkerSkill(" not in worker_source
    assert "if request.worker_agent" not in worker_source
    assert "elif request.worker_agent" not in worker_source


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
