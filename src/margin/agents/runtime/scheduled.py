"""Scheduled Agent runner using the Main -> Expert -> Worker A2A hierarchy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.agent_runtime.schedules import AgentScheduleRepository, StockAnalysisSchedule
from margin.agents.a2a import InProcessA2ATransport
from margin.agents.context.persistence import ContextPersistence
from margin.agents.context.repository import ContextRepository, MemoryContextRepository
from margin.agents.protocol.execution import AgentRunContext
from margin.agents.protocol.models import AgentExecutionStatus, ContextFact, ContextPack
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.expert_runtime import LLMExpertAgentPlanner
from margin.agents.runtime.hierarchy import (
    HierarchicalPlanExecutor,
    HierarchyExecutionResult,
    register_hierarchy_endpoints,
)
from margin.agents.runtime.main_runtime import (
    GlobalPlan,
    LLMMainAgentPlanner,
    MainPlanValidator,
    MainRuntime,
)
from margin.agents.runtime.scheduled_workers import (
    SCHEDULE_INSPECT_DATA_TOOL,
    VALUATION_START_REFRESH_TOOL,
    ScheduledRuntimeComponents,
    build_scheduled_runtime_components,
)
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityAuthority, CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.gateway import ToolAuditStore, ToolGateway
from margin.config_runtime.bootstrap import SCHEDULED_QUANT_PROFILE_KEY
from margin.config_runtime.models import ConfigReference
from margin.config_runtime.repository import ConfigResolver
from margin.research.llm import LLMProvider

SCHEDULED_AGENT_RUNTIME_VERSION = "scheduled-agent-runtime-v1"
SCHEDULED_EXECUTION_BOUNDARY = "a2a_hierarchical_runtime"


class ScheduledAgentRuntimeRunner:
    """Run due schedules through Main planning and the A2A Agent hierarchy."""

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
        tool_audit_store: ToolAuditStore | None = None,
        worker_checkpointer: Any | None = None,
    ) -> None:
        """Initialize without changing the existing Scheduler-facing contract."""
        self._repository = repository
        self._context_store = context_store
        self._valuation_service = valuation_service
        self._scope_resolver = scope_resolver
        self._llm_provider_factory = llm_provider_factory
        self._config_resolver = config_resolver
        self._context_repository = context_repository or MemoryContextRepository()
        self._context_persistence = ContextPersistence(
            context_store=context_store,
            context_repository=self._context_repository,
        )
        self._tool_audit_store = tool_audit_store or InMemoryToolAuditStore()
        self._worker_checkpointer = worker_checkpointer

    def run_once(self, *, now: datetime | None = None) -> int:
        """Trigger each due enabled schedule once."""
        resolved_now = now or datetime.now(UTC)
        processed = 0
        for schedule in self._repository.list_due_stock_analysis_schedules(now=resolved_now):
            self._trigger(schedule, now=resolved_now)
            processed += 1
        return processed

    def _trigger(self, schedule: StockAnalysisSchedule, *, now: datetime) -> None:
        """Plan, dispatch, review, and persist one scheduled research intent."""
        local_date = now.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        run_id = _scheduled_run_id(
            schedule=schedule,
            local_date=local_date,
            triggered_at=now,
        )
        context_pack_ref = f"ctxpack_{run_id}_scheduled"
        scheduled_task_intent = _scheduled_task_intent(schedule)
        context_pack = _scheduled_context_pack(
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            schedule=schedule,
            scheduled_task_intent=scheduled_task_intent,
        )
        self._context_persistence.persist_context_pack(context_pack)

        components = build_scheduled_runtime_components(
            valuation_service=self._valuation_service,
            checkpointer=self._worker_checkpointer,
        )
        capability_registry = CapabilityRegistry(
            domain_cards=components.domain_cards,
            worker_cards=components.worker_cards,
            executor_registry=components.executor_registry,
            tool_catalog=components.tool_catalog,
        )
        contract_report = capability_registry.validate_startup_contracts()
        if not contract_report.valid:
            raise RuntimeError(
                "scheduled capability contract failed: " + ",".join(contract_report.errors)
            )

        root_token = _scheduled_root_capability_token(run_id)
        main_runtime = MainRuntime(
            domain_cards=components.domain_cards,
            planner=LLMMainAgentPlanner(llm_provider=self._llm_provider_factory()),
            capability_registry=capability_registry,
        )
        global_plan = main_runtime.create_global_plan(
            run_id=run_id,
            run_type="scheduled_stock_analysis",
            user_goal=_scheduled_task_prompt(schedule),
            context_pack=context_pack,
            capability_token=root_token,
        )
        plan_validation = MainPlanValidator(components.domain_cards).validate(global_plan)
        if not plan_validation.valid:
            raise RuntimeError(
                "scheduled MainAgent plan validation failed: "
                + ",".join(plan_validation.error_codes)
            )

        quant_profile, quant_profile_ref = self._resolve_quant_profile(now)
        config_snapshot_id = self._config_snapshot_id(
            run_id=run_id,
            decision_at=now,
            quant_profile_ref=quant_profile_ref,
        )
        resolved_scope = self._scope_resolver(schedule.scope_version_id)
        plan_artifact = _scheduled_plan_artifact(
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            global_plan=global_plan,
            plan_validation=plan_validation,
            scheduled_task_intent=scheduled_task_intent,
            components=components,
        )
        self._context_store.add_artifact(plan_artifact)
        plan_metadata = _scheduled_plan_metadata(
            run_id=run_id,
            schedule=schedule,
            plan_artifact_id=plan_artifact.artifact_id,
            global_plan=global_plan,
            plan_validation=plan_validation,
            scheduled_task_intent=scheduled_task_intent,
            config_snapshot_id=config_snapshot_id,
            quant_profile=quant_profile,
        )

        authority = CapabilityAuthority()
        for token in main_runtime.issued_tokens.values():
            authority.issue(token)
        transport = InProcessA2ATransport()
        tool_gateway = ToolGateway(
            catalog=components.tool_catalog,
            audit_store=self._tool_audit_store,
            capability_authority=authority,
        )
        worker_runtime = WorkerRuntime(executor_registry=components.executor_registry)
        register_hierarchy_endpoints(
            transport=transport,
            domain_cards=components.domain_cards,
            worker_cards=components.worker_cards,
            expert_planner_factory=lambda: LLMExpertAgentPlanner(
                llm_provider=self._llm_provider_factory()
            ),
            capability_registry=capability_registry,
            capability_authority=authority,
            worker_runtime=worker_runtime,
            context_store=self._context_store,
            context_repository=self._context_repository,
            tool_gateway=tool_gateway,
            tool_audit_store=self._tool_audit_store,
            llm_provider_factory=self._llm_provider_factory,
        )
        hierarchy_result = HierarchicalPlanExecutor(
            transport=transport,
            max_concurrency=2,
        ).execute(
            plan=global_plan,
            run_context=AgentRunContext(
                run_id=run_id,
                trigger="scheduled",
                goal=_scheduled_task_prompt(schedule),
                language="zh",
                scope_version_id=resolved_scope,
                universe=schedule.universe,
                metadata={
                    "schedule_id": schedule.schedule_id,
                    "universe": schedule.universe,
                    "requested_scope_version_id": schedule.scope_version_id,
                    "resolved_scope_version_id": resolved_scope,
                    "decision_at": now.isoformat(),
                    "valuation_idempotency_key": f"{schedule.schedule_id}:{local_date}",
                    "plan_metadata": plan_metadata,
                },
            ),
            context_pack=context_pack,
        )
        self._persist_hierarchy_artifacts(
            hierarchy_result,
            context_pack_ref=context_pack_ref,
        )
        self._context_store.add_artifact(
            _scheduled_main_review_artifact(
                run_id=run_id,
                global_plan=global_plan,
                hierarchy_result=hierarchy_result,
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

    def _config_snapshot_id(
        self,
        *,
        run_id: str,
        decision_at: datetime,
        quant_profile_ref: ConfigReference | None,
    ) -> str | None:
        if self._config_resolver is None or quant_profile_ref is None:
            return None
        snapshot = self._config_resolver.create_resolution_snapshot(
            run_id=run_id,
            decision_at=decision_at,
            references=(quant_profile_ref,),
        )
        return snapshot.snapshot_id

    def _persist_hierarchy_artifacts(
        self,
        result: HierarchyExecutionResult,
        *,
        context_pack_ref: str,
    ) -> None:
        """Persist Worker artifacts and Expert-reviewed capsule/audit artifacts."""
        for execution in result.domain_executions:
            self._context_repository.save_domain_capsule(
                execution.capsule,
                domain_task_id=execution.result.domain_task_id,
                expert_agent=execution.result.domain_agent,
                output_artifact_refs=execution.capsule.artifact_refs,
                audit_report_ref=execution.audit.audit_report_id,
                token_estimate=len(execution.capsule.model_dump_json()),
            )
            self._context_repository.record_lineage_edge(
                run_id=execution.result.run_id,
                from_ref=execution.capsule.capsule_id,
                to_ref=context_pack_ref,
                edge_type="source_ref",
            )
            for artifact_ref in execution.capsule.artifact_refs:
                self._context_repository.record_lineage_edge(
                    run_id=execution.result.run_id,
                    from_ref=execution.capsule.capsule_id,
                    to_ref=artifact_ref,
                    edge_type="source_ref",
                )
            for artifact in execution.artifacts:
                if self._context_store.get_artifact(artifact.artifact_id) is None:
                    self._context_store.add_artifact(artifact)


def _scheduled_run_id(
    *,
    schedule: StockAnalysisSchedule,
    local_date: str,
    triggered_at: datetime,
) -> str:
    """Build a traceable ID unique to one scheduled trigger attempt."""
    schedule_key = sha256(schedule.schedule_id.encode("utf-8")).hexdigest()[:8]
    trigger_timestamp = triggered_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        f"ar_sched_{local_date.replace('-', '')}_"
        f"{schedule.hour:02d}{schedule.minute:02d}_{schedule_key}_{trigger_timestamp}"
    )


def _scheduled_plan_artifact(
    *,
    run_id: str,
    context_pack_ref: str,
    global_plan: GlobalPlan,
    plan_validation: Any,
    scheduled_task_intent: dict[str, str],
    components: ScheduledRuntimeComponents,
) -> Any:
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}_scheduled_global_plan",
        run_id=run_id,
        artifact_type="scheduled_global_plan",
        producer_agent="MainAgent",
        payload_json={
            "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
            "scheduled_planner_mode": "dynamic_main_agent_planner",
            "execution_boundary": SCHEDULED_EXECUTION_BOUNDARY,
            "dispatch_protocol": "A2A",
            "worker_runtime": "langgraph",
            "global_plan": global_plan.model_dump(mode="json"),
            "scheduled_task_intent": scheduled_task_intent,
            "main_agent_plan": _global_plan_summary(global_plan),
            "plan_validation": plan_validation.model_dump(mode="json"),
            "context_pack_ref": context_pack_ref,
            "l3_worker_skills": [
                f"{card.name}.{skill.skill_id}"
                for card in components.worker_cards
                for skill in card.skills
                if not skill.planned_only
            ],
            "tool_names": [binding.tool_spec.tool_name for binding in components.bindings],
        },
        source_refs=(global_plan.planning_prompt_ref,),
    )


def _scheduled_plan_metadata(
    *,
    run_id: str,
    schedule: StockAnalysisSchedule,
    plan_artifact_id: str,
    global_plan: GlobalPlan,
    plan_validation: Any,
    scheduled_task_intent: dict[str, str],
    config_snapshot_id: str | None,
    quant_profile: Any,
) -> dict[str, Any]:
    return {
        "agent_runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
        "agent_run_id": run_id,
        "schedule_id": schedule.schedule_id,
        "universe": schedule.universe,
        "global_plan": {
            "artifact_id": plan_artifact_id,
            "created_by": global_plan.created_by,
            "domain_task_count": len(global_plan.domain_tasks),
        },
        "scheduled_task_intent": scheduled_task_intent,
        "main_agent_plan": _global_plan_summary(global_plan),
        "plan_validation": plan_validation.model_dump(mode="json"),
        "config_resolution_snapshot_id": config_snapshot_id,
        "quant_agent_strategy_profile": quant_profile.to_metadata(),
        "quant_strategy": quant_profile.to_quant_strategy_metadata(),
        "execution_boundary": SCHEDULED_EXECUTION_BOUNDARY,
        "dispatch_protocol": "A2A",
        "worker_runtime": "langgraph",
    }


def _scheduled_main_review_artifact(
    *,
    run_id: str,
    global_plan: GlobalPlan,
    hierarchy_result: HierarchyExecutionResult,
) -> Any:
    completed_ids = {
        execution.result.domain_task_id
        for execution in hierarchy_result.domain_executions
        if execution.result.status is AgentExecutionStatus.SUCCEEDED
    }
    required_ids = {task.domain_task_id for task in global_plan.domain_tasks}
    missing_ids = tuple(sorted(required_ids - completed_ids))
    successful_count = len(completed_ids)
    if not required_ids:
        decision = "blocked"
    elif not missing_ids:
        decision = "dispatched"
    elif successful_count:
        decision = "partial"
    else:
        decision = "blocked"
    all_artifacts = tuple(
        artifact
        for execution in hierarchy_result.domain_executions
        for artifact in execution.artifacts
    )
    refresh_run_id = next(
        (
            str(artifact.payload_json.get("valuation_refresh_run_id") or "")
            for artifact in all_artifacts
            if artifact.artifact_type == "valuation_refresh"
        ),
        "",
    )
    worker_results = tuple(
        result
        for execution in hierarchy_result.domain_executions
        for result in execution.worker_results
    )
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}_l3_execution_report",
        run_id=run_id,
        artifact_type="l3_execution_report",
        producer_agent="MainAgent",
        payload_json={
            "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
            "execution_boundary": SCHEDULED_EXECUTION_BOUNDARY,
            "dispatch_protocol": "A2A",
            "worker_runtime": "langgraph",
            "completion_scope": "refresh_dispatch_only",
            "research_status": (
                "refresh_pending" if decision == "dispatched" else "incomplete"
            ),
            "main_agent_review": {
                "decision": decision,
                "required_domain_task_ids": sorted(required_ids),
                "completed_domain_task_ids": sorted(completed_ids),
                "missing_domain_task_ids": list(missing_ids),
                "planner_messages": list(global_plan.planner_messages),
            },
            "domain_reviews": [
                {
                    "domain_task_id": execution.result.domain_task_id,
                    "domain_agent": execution.result.domain_agent,
                    "status": execution.result.status,
                    "audit_ref": execution.result.domain_audit_report_ref,
                    "capsule_ref": execution.result.domain_context_capsule_ref,
                }
                for execution in hierarchy_result.domain_executions
            ],
            "workers": [
                {
                    "worker_agent": result.worker_agent,
                    "skill_id": result.skill_id,
                    "status": result.status,
                    "output_artifact_refs": list(result.output_artifact_refs),
                    "audit_event_refs": list(result.audit_event_refs),
                }
                for result in worker_results
            ],
            "a2a_task_ids": list(hierarchy_result.a2a_task_ids),
            "valuation_refresh_run_id": refresh_run_id,
            "finished_at": datetime.now(UTC).isoformat(),
        },
        source_refs=tuple(artifact.artifact_id for artifact in all_artifacts),
    )


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
                    "Scheduled work uses Main planning, A2A Expert/Worker dispatch, "
                    "Expert review, and Main review."
                ),
                confidence=1.0,
                fact_type="data_status",
                subject_type="run",
                subject_id=run_id,
                value_json={
                    "scheduled_planner_mode": "dynamic_main_agent_planner",
                    "execution_boundary": SCHEDULED_EXECUTION_BOUNDARY,
                    "dispatch_protocol": "A2A",
                    "worker_runtime": "langgraph",
                },
                source_refs=(f"schedule:{schedule.schedule_id}",),
            ),
        ),
        compression_policy_version="scheduled-main-planning-v2",
    )


def _scheduled_root_capability_token(run_id: str) -> CapabilityToken:
    """Return the least-privilege root token delegated through both Agent layers."""
    return CapabilityToken(
        token_id=f"cap_{run_id}_scheduled_root",
        run_id=run_id,
        issued_by="system",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_PROVIDER_STATUS,
            DataAccessPolicy.READ_ANALYSIS_MART,
        ),
        production_write=(
            ProductionWritePolicy.WRITE_CONTEXT_ONLY,
            ProductionWritePolicy.WRITE_ANALYSIS_MART,
            ProductionWritePolicy.WRITE_DASHBOARD_PROJECTION,
        ),
        tool_policy=(
            ToolPolicy.DATA_SYNC_TOOLS,
            ToolPolicy.QUANT_TOOLS,
        ),
        allowed_artifact_types=(
            "scheduled_global_plan",
            "data_readiness",
            "valuation_refresh",
            "quant_result",
            "worker_activity",
            "domain_context_capsule",
            "domain_audit_report",
            "l3_execution_report",
        ),
        allowed_tool_names=(
            SCHEDULE_INSPECT_DATA_TOOL,
            VALUATION_START_REFRESH_TOOL,
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=2),
        max_tool_calls=4,
        max_result_bytes=128_000,
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
                "depends_on": list(task.depends_on),
            }
            for task in global_plan.domain_tasks
        ],
        "planner_messages": list(global_plan.planner_messages),
    }
