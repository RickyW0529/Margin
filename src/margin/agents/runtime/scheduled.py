"""Scheduled v1 Agent runtime runner with real L3 worker execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.agent_runtime.schedules import AgentScheduleRepository, StockAnalysisSchedule
from margin.agents.cards.registry import default_domain_agent_cards, default_worker_agent_cards
from margin.agents.context.persistence import ContextPersistence
from margin.agents.context.repository import ContextRepository, MemoryContextRepository
from margin.agents.protocol.models import ContextFact, ContextPack, DomainTaskRequest
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.runtime.main_runtime import (
    GlobalPlan,
    LLMMainAgentPlanner,
    MainPlanValidator,
    MainRuntime,
)
from margin.agents.runtime.scheduled_l3 import run_scheduled_l3_pipeline
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.catalog import default_tool_catalog
from margin.config_runtime.bootstrap import SCHEDULED_QUANT_PROFILE_KEY
from margin.config_runtime.models import ConfigReference
from margin.config_runtime.repository import ConfigResolver
from margin.research.llm import LLMProvider

SCHEDULED_AGENT_RUNTIME_VERSION = "scheduled-agent-runtime-v1"


class _ValuationRefreshExecutor:
    """Marker executor registered so planners can see the quant L3 skill."""

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        """Scheduled path invokes ValuationRefreshL3Worker directly."""
        raise NotImplementedError("scheduled L3 pipeline executes this skill directly")


class _DataInspectionExecutor:
    """Marker executor registered so planners can see the data L3 skill."""

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        """Scheduled path invokes DataInspectionL3Worker directly."""
        raise NotImplementedError("scheduled L3 pipeline executes this skill directly")


class ScheduledAgentRuntimeRunner:
    """Run due stock-analysis schedules through L1 plan + real L3 workers."""

    def __init__(
        self,
        *,
        repository: AgentScheduleRepository,
        context_store: AgentContextStore,
        valuation_service: Any,
        scope_resolver: Callable[[str], str],
        llm_provider_factory: Callable[[], LLMProvider],
        config_resolver: ConfigResolver | None = None,
        context_repository: ContextRepository | None = None,
    ) -> None:
        """Initialize the scheduled v1 Agent runtime runner."""
        self._repository = repository
        self._context_store = context_store
        self._valuation_service = valuation_service
        self._scope_resolver = scope_resolver
        self._llm_provider_factory = llm_provider_factory
        self._config_resolver = config_resolver
        self._context_persistence = ContextPersistence(
            context_store=context_store,
            context_repository=context_repository or MemoryContextRepository(),
        )

    def run_once(self, *, now: datetime | None = None) -> int:
        """Trigger each due enabled schedule once."""
        resolved_now = now or datetime.now(UTC)
        processed = 0
        for schedule in self._repository.list_due_stock_analysis_schedules(now=resolved_now):
            self._trigger(schedule, now=resolved_now)
            processed += 1
        return processed

    def _trigger(self, schedule: StockAnalysisSchedule, *, now: datetime) -> None:
        """Plan, execute L3 workers, and record schedule progress."""
        local_date = now.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        run_id = f"ar_sched_{local_date.replace('-', '')}_{schedule.hour:02d}{schedule.minute:02d}"
        context_pack_ref = f"ctxpack_{run_id}_scheduled"
        scheduled_task_intent = _scheduled_task_intent(schedule)
        context_pack = _scheduled_context_pack(
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            schedule=schedule,
            scheduled_task_intent=scheduled_task_intent,
        )
        self._context_persistence.persist_context_pack(context_pack)

        executor_registry = _scheduled_executor_registry()
        domain_cards = default_domain_agent_cards()
        capability_registry = CapabilityRegistry(
            domain_cards=domain_cards,
            worker_cards=default_worker_agent_cards(),
            executor_registry=executor_registry,
            tool_catalog=default_tool_catalog(),
        )
        root_token = _scheduled_root_capability_token(run_id)
        global_plan = MainRuntime(
            domain_cards=domain_cards,
            planner=LLMMainAgentPlanner(llm_provider=self._llm_provider_factory()),
            capability_registry=capability_registry,
        ).create_global_plan(
            run_id=run_id,
            run_type="scheduled_stock_analysis",
            user_goal=_scheduled_task_prompt(schedule),
            context_pack=context_pack,
            capability_token=root_token,
        )
        # Ensure L3 domain tasks exist even when the LLM planner returns none.
        global_plan = _ensure_scheduled_domain_tasks(
            global_plan,
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            capability_token_ref=root_token.token_id,
            schedule=schedule,
        )
        plan_validation = MainPlanValidator(domain_cards).validate(global_plan)
        if not plan_validation.valid:
            raise RuntimeError(
                "scheduled MainAgent plan validation failed: "
                + ",".join(plan_validation.error_codes)
            )

        quant_profile, quant_profile_ref = self._resolve_quant_profile(now)
        quant_profile_metadata = quant_profile.to_metadata()
        config_references = []
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

        plan_artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_scheduled_global_plan",
            run_id=run_id,
            artifact_type="scheduled_global_plan",
            producer_agent="MainAgent",
            payload_json={
                "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
                "scheduled_planner_mode": "dynamic_main_agent_planner",
                "execution_boundary": "l3_worker_runtime",
                "global_plan": global_plan.model_dump(mode="json"),
                "scheduled_task_intent": scheduled_task_intent,
                "main_agent_plan": _global_plan_summary(global_plan),
                "plan_validation": plan_validation.model_dump(mode="json"),
                "context_pack_ref": context_pack_ref,
                "l3_worker_skills": [
                    "DataInspectionWorker.scheduled_data_readiness",
                    "ValuationRefreshWorker.start_valuation_refresh",
                ],
            },
            source_refs=(global_plan.planning_prompt_ref,),
        )
        self._context_store.add_artifact(plan_artifact)

        plan_metadata = {
            "agent_runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
            "agent_run_id": run_id,
            "schedule_id": schedule.schedule_id,
            "universe": schedule.universe,
            "global_plan": {
                "artifact_id": plan_artifact.artifact_id,
                "created_by": global_plan.created_by,
                "domain_task_count": len(global_plan.domain_tasks),
            },
            "scheduled_task_intent": scheduled_task_intent,
            "main_agent_plan": _global_plan_summary(global_plan),
            "plan_validation": plan_validation.model_dump(mode="json"),
            "config_resolution_snapshot_id": config_snapshot_id,
            "quant_agent_strategy_profile": quant_profile_metadata,
            "quant_strategy": quant_profile.to_quant_strategy_metadata(),
            "execution_boundary": "l3_worker_runtime",
        }
        l3_result = run_scheduled_l3_pipeline(
            run_id=run_id,
            schedule=schedule,
            scope_version_id=resolved_scope,
            context_store=self._context_store,
            valuation_service=self._valuation_service,
            now=now,
            idempotency_key=f"{schedule.schedule_id}:{local_date}",
            plan_metadata=plan_metadata,
        )
        # Keep a stable valuation_refresh artifact alias expected by dashboards/tests.
        # The L3 worker already wrote the primary valuation_refresh artifact.
        _ = l3_result

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


def _scheduled_executor_registry() -> ExecutorRegistry:
    """Register the L3 skills visible to scheduled MainAgent planning."""
    registry = ExecutorRegistry()
    registry.register_spec(
        ExecutorSpec(
            agent_name="DataInspectionWorker",
            skill_id="scheduled_data_readiness",
            executor=_DataInspectionExecutor(),
            runtime="deterministic",
            output_artifact_types=("data_readiness",),
            domain="data",
        )
    )
    registry.register_spec(
        ExecutorSpec(
            agent_name="ValuationRefreshWorker",
            skill_id="start_valuation_refresh",
            executor=_ValuationRefreshExecutor(),
            runtime="deterministic",
            output_artifact_types=("valuation_refresh",),
            domain="quant",
        )
    )
    return registry


def _ensure_scheduled_domain_tasks(
    global_plan: GlobalPlan,
    *,
    run_id: str,
    context_pack_ref: str,
    capability_token_ref: str,
    schedule: StockAnalysisSchedule,
) -> GlobalPlan:
    """Attach fixed L3 domain tasks when the planner returns an empty task list."""
    if global_plan.domain_tasks:
        return global_plan
    tasks = (
        DomainTaskRequest(
            run_id=run_id,
            domain_task_id=f"dt_{run_id}_data",
            to_domain_agent="DataExpertAgent",
            domain="data",
            user_intent_summary=f"scheduled {schedule.universe}",
            task_goal="Check PIT data readiness before valuation refresh.",
            required_output_types=("data_readiness",),
            input_context_pack_ref=context_pack_ref,
            capability_token_ref=capability_token_ref,
            constraints={"l3_worker": "DataInspectionWorker.scheduled_data_readiness"},
            token_budget=2000,
            deadline_ms=30_000,
            idempotency_key=f"{run_id}:data",
        ),
        DomainTaskRequest(
            run_id=run_id,
            domain_task_id=f"dt_{run_id}_quant",
            to_domain_agent="QuantExpertAgent",
            domain="quant",
            user_intent_summary=f"scheduled {schedule.universe}",
            task_goal="Run valuation discovery refresh for the research universe.",
            required_output_types=("valuation_refresh", "quant_result"),
            input_context_pack_ref=context_pack_ref,
            capability_token_ref=capability_token_ref,
            constraints={"l3_worker": "ValuationRefreshWorker.start_valuation_refresh"},
            token_budget=4000,
            deadline_ms=120_000,
            idempotency_key=f"{run_id}:quant",
        ),
    )
    return global_plan.model_copy(update={"domain_tasks": tasks})


def _scheduled_task_intent(schedule: StockAnalysisSchedule) -> dict[str, str]:
    """Return the durable scheduled intent metadata supplied to MainAgent."""
    return {
        "planner": "MainAgent",
        "intent_type": "scheduled_stock_analysis",
        "universe": schedule.universe,
        "scope_version_id": schedule.scope_version_id,
        "language": "zh",
    }


def _scheduled_task_prompt(schedule: StockAnalysisSchedule) -> str:
    """Return the natural-language scheduled goal given to MainAgent."""
    return (
        f"今天对 {schedule.universe} 做本地研究更新。先检查数据和 PIT 可用性；"
        "然后让量化专家启动估值发现刷新流水线，发布 Dashboard 研究候选。"
    )


def _scheduled_context_pack(
    *,
    run_id: str,
    context_pack_ref: str,
    schedule: StockAnalysisSchedule,
    scheduled_task_intent: dict[str, str],
) -> ContextPack:
    """Build the bounded ContextPack for scheduled MainAgent planning."""
    return ContextPack(
        context_pack_id=context_pack_ref,
        run_id=run_id,
        requester_agent="Scheduler",
        target_agent="MainAgent",
        purpose="scheduled_stock_analysis_planning",
        token_budget=6000,
        facts=(
            ContextFact(
                fact_id=f"fact_{run_id}_intent",
                statement=_scheduled_task_prompt(schedule),
                confidence=1.0,
                fact_type="user_constraint",
                source_refs=(f"schedule:{schedule.schedule_id}",),
            ),
            ContextFact(
                fact_id=f"fact_{run_id}_scope",
                statement=(
                    f"Schedule scope={scheduled_task_intent['scope_version_id']}, "
                    f"universe={scheduled_task_intent['universe']}."
                ),
                confidence=1.0,
                fact_type="platform_status",
                source_refs=(f"schedule:{schedule.schedule_id}",),
            ),
            ContextFact(
                fact_id=f"fact_{run_id}_scheduled_runtime_status",
                statement=(
                    "Scheduled v1 plans through MainAgent then executes fixed L3 workers "
                    "(data readiness + valuation refresh)."
                ),
                confidence=1.0,
                fact_type="data_status",
                subject_type="run",
                subject_id=run_id,
                value_json={
                    "scheduled_planner_mode": "dynamic_main_agent_planner",
                    "execution_boundary": "l3_worker_runtime",
                    "worker_execution": "l3_pipeline",
                },
                source_refs=(f"schedule:{schedule.schedule_id}",),
            ),
        ),
        compression_policy_version="scheduled-main-planning-v1",
    )


def _scheduled_root_capability_token(run_id: str) -> CapabilityToken:
    """Return the root token MainAgent can delegate to scheduled ExpertAgents."""
    return CapabilityToken(
        token_id=f"cap_{run_id}_scheduled_root",
        run_id=run_id,
        issued_by="system",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_ANALYSIS_MART,
            DataAccessPolicy.READ_EVIDENCE,
            DataAccessPolicy.READ_VECTOR_INDEX,
            DataAccessPolicy.READ_PROVIDER_STATUS,
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(
            ToolPolicy.READ_ONLY_TOOLS,
            ToolPolicy.RETRIEVAL_TOOLS,
            ToolPolicy.QUANT_TOOLS,
            ToolPolicy.DATA_SYNC_TOOLS,
        ),
        allowed_artifact_types=(
            "data_context_capsule",
            "data_readiness",
            "quant_context_capsule",
            "quant_result",
            "valuation_refresh",
            "l3_execution_report",
            "evidence_context_capsule",
            "evidence_package",
            "stock_research_context_capsule",
            "dashboard_projection_event",
        ),
        allowed_tool_names=(
            "dashboard.read_candidates",
            "analysis_mart.read_snapshot",
            "quant.run_screen",
            "evidence.read_package",
            "provider.read_status",
            "warehouse.describe_schema",
            "warehouse.resolve_security",
            "warehouse.discover_indicators",
            "warehouse.query_indicator_history",
            "warehouse.query_data_freshness",
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=2),
        max_tool_calls=16,
        max_result_bytes=96_000,
        can_delegate=True,
        delegation_depth_remaining=2,
    )


def _global_plan_summary(global_plan: GlobalPlan) -> dict[str, Any]:
    """Return a compact, user-safe summary of the dynamic MainAgent plan."""
    return {
        "planning_mode": global_plan.planning_mode,
        "planning_prompt_ref": global_plan.planning_prompt_ref,
        "planning_prompt_hash": global_plan.planning_prompt_hash,
        "domain_agents": [task.to_domain_agent for task in global_plan.domain_tasks],
        "domain_tasks": [
            {
                "domain_task_id": task.domain_task_id,
                "to_domain_agent": task.to_domain_agent,
                "domain": task.domain,
                "task_goal": task.task_goal,
            }
            for task in global_plan.domain_tasks
        ],
        "planner_messages": list(global_plan.planner_messages),
    }
