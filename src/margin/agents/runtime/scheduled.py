"""Scheduled v1 Agent runtime runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.agent_runtime.schedules import AgentScheduleRepository, StockAnalysisSchedule
from margin.agents.cards.registry import default_domain_agent_cards, default_worker_agent_cards
from margin.agents.protocol.models import ContextFact, ContextPack
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.executor_registry import ExecutorRegistry
from margin.agents.runtime.main_runtime import (
    GlobalPlan,
    LLMMainAgentPlanner,
    MainPlanValidator,
    MainRuntime,
)
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


class ScheduledAgentRuntimeRunner:
    """Run due stock-analysis schedules through the v1 Agent control plane."""

    def __init__(
        self,
        *,
        repository: AgentScheduleRepository,
        context_store: AgentContextStore,
        valuation_service: Any,
        scope_resolver: Callable[[str], str],
        llm_provider_factory: Callable[[], LLMProvider],
        config_resolver: ConfigResolver | None = None,
    ) -> None:
        """Initialize the scheduled v1 Agent runtime runner."""
        self._repository = repository
        self._context_store = context_store
        self._valuation_service = valuation_service
        self._scope_resolver = scope_resolver
        self._llm_provider_factory = llm_provider_factory
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
        context_pack_ref = f"ctxpack_{run_id}_scheduled"
        scheduled_task_intent = _scheduled_task_intent(schedule)
        context_pack = _scheduled_context_pack(
            run_id=run_id,
            context_pack_ref=context_pack_ref,
            schedule=schedule,
            scheduled_task_intent=scheduled_task_intent,
        )
        domain_cards = default_domain_agent_cards()
        capability_registry = CapabilityRegistry(
            domain_cards=domain_cards,
            worker_cards=default_worker_agent_cards(),
            executor_registry=ExecutorRegistry(),
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
        plan_validation = MainPlanValidator(domain_cards).validate(global_plan)
        if not plan_validation.valid:
            raise RuntimeError(
                "scheduled MainAgent plan validation failed: "
                + ",".join(plan_validation.error_codes)
            )
        plan_artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_scheduled_global_plan",
            run_id=run_id,
            artifact_type="scheduled_global_plan",
            producer_agent="MainAgent",
            payload_json={
                "runtime_version": SCHEDULED_AGENT_RUNTIME_VERSION,
                "scheduled_planner_mode": "dynamic_main_agent_planner",
                "execution_boundary": "valuation_refresh_service",
                "global_plan": global_plan.model_dump(mode="json"),
                "scheduled_task_intent": scheduled_task_intent,
                "main_agent_plan": _global_plan_summary(global_plan),
                "plan_validation": plan_validation.model_dump(mode="json"),
                "context_pack_ref": context_pack_ref,
            },
            source_refs=(global_plan.planning_prompt_ref,),
        )
        self._context_store.add_artifact(plan_artifact)

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
                "scheduled_task_intent": scheduled_task_intent,
                "main_agent_plan": _global_plan_summary(global_plan),
                "plan_validation": plan_validation.model_dump(mode="json"),
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
                    "scheduled_task_intent": scheduled_task_intent,
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
        "然后让量化专家和财报增长专家并行研究。量化线只使用结构化 PIT 数据、"
        "Quant Feature Mart 和 Analysis Mart，不使用 WebSearch。财报线关注业绩大增、"
        "财报/招股说明书/调研中的产品供不应求、行业高景气度上行、市场超预期拓展、"
        "新品上市持续超预期、产品价格中枢持续上涨、供给偏紧、需求旺盛；"
        "已有财报结论时，舆情分析只验证近期信息是否继续支持原结论。"
        "最后融合量化、财报、舆情和风险证据，发布 Dashboard 研究候选。"
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
                    "Scheduled v1 uses dynamic MainAgent planning; valuation refresh "
                    "remains the static execution boundary."
                ),
                confidence=1.0,
                fact_type="data_status",
                subject_type="run",
                subject_id=run_id,
                value_json={
                    "scheduled_planner_mode": "dynamic_main_agent_planner",
                    "execution_boundary": "valuation_refresh_service",
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
            "evidence_context_capsule",
            "evidence_package",
            "stock_research_context_capsule",
            "fundamental_thesis_snapshot",
            "sentiment_delta_report",
            "fusion_research_result",
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
                "required_output_types": list(task.required_output_types),
                "constraints": task.constraints,
            }
            for task in global_plan.domain_tasks
        ],
        "dependency_edges": list(global_plan.domain_dependency_edges),
        "final_answer_requirements": list(global_plan.final_answer_requirements),
        "planner_messages": list(global_plan.planner_messages),
    }
