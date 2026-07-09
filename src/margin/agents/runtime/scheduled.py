"""Scheduled v1 Agent runtime runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.agent_runtime.schedules import AgentScheduleRepository, StockAnalysisSchedule
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.agents.runtime.adapters_v0 import map_v0_flow_to_domain_tasks
from margin.agents.runtime.main_runtime import GlobalPlan
from margin.config_runtime.bootstrap import SCHEDULED_QUANT_PROFILE_KEY
from margin.config_runtime.models import ConfigReference
from margin.config_runtime.repository import ConfigResolver

SCHEDULED_AGENT_RUNTIME_VERSION = "scheduled-agent-runtime-v1"


class ScheduledAgentRuntimeRunner:
    """Run due stock-analysis schedules through the v1 Agent control plane."""

    def __init__(
        self,
        *,
        repository: AgentScheduleRepository,
        context_store: AgentContextStore,
        valuation_service: Any,
        scope_resolver: Callable[[str], str],
        config_resolver: ConfigResolver | None = None,
    ) -> None:
        """Initialize the scheduled v1 Agent runtime runner."""
        self._repository = repository
        self._context_store = context_store
        self._valuation_service = valuation_service
        self._scope_resolver = scope_resolver
        self._config_resolver = config_resolver

    def run_once(self, *, now: datetime | None = None) -> int:
        """Trigger each due enabled schedule once."""
        resolved_now = now or datetime.now(UTC)
        processed = 0
        for schedule in self._repository.list_due_stock_analysis_schedules(now=resolved_now):
            self._trigger(schedule, now=resolved_now)
            processed += 1
        return processed

    def _trigger(self, schedule: StockAnalysisSchedule, *, now: datetime) -> None:
        """Trigger one due schedule."""
        local_date = now.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        run_id = f"ar_sched_{local_date.replace('-', '')}_{schedule.hour:02d}{schedule.minute:02d}"
        scheduled_flow, flow_ref = self._resolve_agent_flow(now)
        context_pack_ref = f"ctxpack_{run_id}_scheduled"
        capability_token_ref = f"cap_{run_id}_scheduled_root"
        domain_tasks = map_v0_flow_to_domain_tasks(
            scheduled_flow,
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            capability_token_ref=capability_token_ref,
        )
        global_plan = GlobalPlan(
            run_id=run_id,
            run_type="scheduled_stock_analysis",
            user_intent=(
                f"daily stock analysis for {schedule.universe} at "
                f"{schedule.hour:02d}:{schedule.minute:02d} {schedule.timezone}"
            ),
            domain_tasks=domain_tasks,
            final_answer_requirements=("dashboard_projection_audited",),
        )
        flow_summary = _scheduled_flow_summary(scheduled_flow)
        plan_artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_scheduled_global_plan",
            run_id=run_id,
            artifact_type="scheduled_global_plan",
            producer_agent="MainAgent",
            payload_json={
                "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
                "global_plan": global_plan.model_dump(mode="json"),
                "agent_flow": flow_summary,
                "context_pack_ref": context_pack_ref,
                "capability_token_ref": capability_token_ref,
            },
            source_refs=(scheduled_flow.flow_id,),
        )
        self._context_store.add_artifact(plan_artifact)

        quant_profile, quant_profile_ref = self._resolve_quant_profile(now)
        quant_profile_metadata = quant_profile.to_metadata()
        config_references = []
        if flow_ref is not None:
            config_references.append(flow_ref)
        if quant_profile_ref is not None:
            config_references.append(quant_profile_ref)
        config_snapshot_id = None
        if self._config_resolver is not None and config_references:
            config_snapshot = self._config_resolver.create_resolution_snapshot(
                run_id=run_id,
                decision_at=now,
                references=tuple(config_references),
            )
            config_snapshot_id = config_snapshot.snapshot_id
        resolved_scope = self._scope_resolver(schedule.scope_version_id)
        refresh_response = self._valuation_service.start_refresh(
            scope_version_id=resolved_scope,
            decision_at=now,
            idempotency_key=f"{schedule.schedule_id}:{local_date}",
            metadata={
                "agent_runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
                "agent_run_id": run_id,
                "schedule_id": schedule.schedule_id,
                "universe": schedule.universe,
                "global_plan": {
                    "artifact_id": plan_artifact.artifact_id,
                    "created_by": global_plan.created_by,
                    "domain_task_count": len(global_plan.domain_tasks),
                },
                "agent_flow": flow_summary,
                "config_resolution_snapshot_id": config_snapshot_id,
                "quant_agent_strategy_profile": quant_profile_metadata,
                "quant_strategy": quant_profile.to_quant_strategy_metadata(),
            },
        )
        refresh_run_id = str(getattr(refresh_response, "run_id", ""))
        self._context_store.add_artifact(
            make_context_artifact(
                artifact_id=f"ctx_{run_id}_valuation_refresh",
                run_id=run_id,
                artifact_type="valuation_refresh",
                producer_agent="QuantExpertAgent",
                payload_json={
                    "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
                    "schedule_id": schedule.schedule_id,
                    "agent_run_id": run_id,
                    "global_plan_ref": plan_artifact.artifact_id,
                    "config_resolution_snapshot_id": config_snapshot_id,
                    "domain_tasks": [
                        {
                            "domain_task_id": task.domain_task_id,
                            "to_domain_agent": task.to_domain_agent,
                            "domain": task.domain,
                        }
                        for task in global_plan.domain_tasks
                    ],
                    "scope_version_id": resolved_scope,
                    "requested_scope_version_id": schedule.scope_version_id,
                    "universe": schedule.universe,
                    "quant_agent_strategy_profile": quant_profile_metadata,
                    "decision_at": now.isoformat(),
                    "valuation_refresh_run_id": refresh_run_id,
                    "dashboard_projection": "expected_after_refresh",
                },
                source_refs=(plan_artifact.artifact_id, refresh_run_id or "valuation_refresh"),
            )
        )
        self._repository.save_stock_analysis_schedule(
            schedule.model_copy(
                update={
                    "last_triggered_at": now,
                    "updated_at": now,
                }
            )
        )

    def _resolve_quant_profile(self, decision_at: datetime) -> tuple[Any, ConfigReference | None]:
        """Resolve the scheduled Quant profile from DB with a local fallback."""
        if self._config_resolver is None:
            return current_quant_agent_strategy_profile(), None
        try:
            version = self._config_resolver.resolve_quant_agent_profile(
                profile_key=SCHEDULED_QUANT_PROFILE_KEY,
                decision_at=decision_at,
            )
            return (
                version.to_profile(),
                ConfigReference.from_version("quant_agent_profile", version),
            )
        except LookupError:
            return current_quant_agent_strategy_profile(), None

    def _resolve_agent_flow(self, decision_at: datetime) -> tuple[Any, ConfigReference | None]:
        """Resolve the scheduled Agent flow from DB with a local fallback."""
        if self._config_resolver is None:
            return load_scheduled_stock_analysis_flow(), None
        try:
            version = self._config_resolver.resolve_agent_flow(
                flow_id="scheduled_stock_analysis",
                decision_at=decision_at,
            )
            return version.to_flow(), ConfigReference.from_version("agent_flow", version)
        except LookupError:
            return load_scheduled_stock_analysis_flow(), None


def _scheduled_flow_summary(scheduled_flow: Any) -> dict[str, Any]:
    """Return a compact DAG summary for orchestration metadata and UI."""
    return {
        "flow_id": scheduled_flow.flow_id,
        "version": scheduled_flow.version,
        "runtime_owner": "agents.runtime.scheduled",
        "dependency_waves": [
            [step.step_id for step in wave] for wave in scheduled_flow.dependency_waves()
        ],
        "branches": {
            "quant": ["quant_analysis"],
            "fundamental": [
                "performance_growth_scout",
                "rag_coverage_gate",
                "fundamental_analysis",
                "sentiment_monitor",
            ],
            "fusion": ["fusion_research"],
        },
        "quant_branch_uses_websearch": False,
    }
