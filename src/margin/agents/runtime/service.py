"""Application-facing v1 Agent runtime service."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from margin.agent_runtime.context_store import (
    AgentContextStore,
    ContextArtifact,
    make_context_artifact,
)
from margin.agent_runtime.models import (
    AgentExecutionStatus as RuntimeAgentExecutionStatus,
)
from margin.agent_runtime.models import (
    AgentPermissionMode,
    AgentRun,
    AgentRunType,
)
from margin.agents.a2a import InProcessA2ATransport
from margin.agents.cards.registry import default_domain_agent_cards, default_worker_agent_cards
from margin.agents.context.persistence import ContextPersistence
from margin.agents.context.readiness_builder import DataReadinessBuilder
from margin.agents.context.repository import ContextRepository, MemoryContextRepository
from margin.agents.context.router import ContextRouter
from margin.agents.context.turn_context import ResolvedTurnContext, resolve_turn_context
from margin.agents.protocol.execution import AgentRunContext
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    FinalUserAnswerArtifact,
)
from margin.agents.runtime.audit_pipeline import AuditPipeline
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.runtime.expert_runtime import LLMExpertAgentPlanner
from margin.agents.runtime.hierarchy import (
    HierarchicalPlanExecutor,
    register_hierarchy_endpoints,
)
from margin.agents.runtime.langgraph_worker import LangGraphWorkerExecutor
from margin.agents.runtime.main_runtime import GlobalPlan, LLMMainAgentPlanner, MainRuntime
from margin.agents.runtime.worker_executors import (
    DataQuestionWorkerExecutor,
    GeneralQnaWorkerExecutor,
)
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityAuthority, CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import default_tool_catalog
from margin.agents.tools.gateway import ToolAuditStore, ToolGateway
from margin.agents.tools.workspace import register_workspace_tools
from margin.agents.workers.data_question_worker import DataQuestionWorker
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import LLMProvider, strip_thinking_blocks

USER_QNA_RUNTIME_VERSION = "agent-runtime-v1-user-qna"
_CONTROL_PLANE_ARTIFACT_TYPES = (
    "data_readiness",
    "domain_audit_report",
    "domain_context_capsule",
    "final_audit_report",
    "final_user_answer",
    "writing_revision",
)
@dataclass(frozen=True)
class UserQnaCommand:
    """One user-facing Q&A command entering the v1 runtime."""

    run_id: str
    scope_version_id: str
    message: str
    universe: str
    language: Literal["zh", "en"]
    conversation_context: Sequence[dict[str, str]] = ()
    resolved_turn_context: ResolvedTurnContext | None = None
    allow_workspace_tools: bool = False


@dataclass(frozen=True)
class GuardrailSummary:
    """Frontend-safe guardrail result."""

    allowed: bool
    decision: str
    summary: str
    triggered_policies: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTraceStep:
    """One user-visible v1 Agent trace row."""

    step_id: str
    expert_agent_name: str
    skill_id: str
    status: AgentExecutionStatus


@dataclass(frozen=True)
class AgentTraceActivity:
    """Safe execution activity, never prompts, raw errors, or private reasoning."""

    activity_id: str
    stage: Literal["planning", "execution", "validation"]
    actor: str
    action: str
    status: AgentExecutionStatus
    summary: str
    tool_name: str | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainAnswerFragment:
    """One domain's user-safe answer fragment."""

    domain_agent: str
    domain: str
    answer: str
    capsule_ref: str
    status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED


@dataclass(frozen=True)
class UserQnaRunResult:
    """Result returned by the v1 runtime to the API boundary."""

    answer: str
    guardrail: GuardrailSummary
    global_plan: GlobalPlan
    trace_steps: tuple[AgentTraceStep, ...]
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]
    final_answer: FinalUserAnswerArtifact
    activities: tuple[AgentTraceActivity, ...] = ()


class AgentInputBlockedError(RuntimeError):
    """Raised when the v1 input guardrail blocks a user request."""

    def __init__(self, guardrail: GuardrailSummary) -> None:
        """Initialize with the safe guardrail summary."""
        super().__init__(guardrail.summary)
        self.guardrail = guardrail


class AgentRuntimeUnavailableError(RuntimeError):
    """Raised when a required v1 runtime dependency is unavailable."""


class AgentRuntimeService:
    """Run user-facing Agent workflows through the v1 control-plane protocol."""

    def __init__(
        self,
        *,
        context_store: AgentContextStore,
        context_repository: ContextRepository | None = None,
        dashboard_services: DashboardServiceBundle,
        llm_provider_factory: Callable[[], LLMProvider],
        warehouse_repository: Any | None = None,
        main_runtime: MainRuntime | None = None,
        audit_pipeline: AuditPipeline | None = None,
        tool_audit_store: ToolAuditStore | None = None,
        workspace_root: str | Path | None = None,
        code_tools_enabled: bool = False,
        main_max_concurrency: int = 1,
        expert_max_concurrency: int = 1,
        firecrawl_adapter: Any | None = None,
    ) -> None:
        """Initialize the application-facing v1 Agent runtime service."""
        self._context_store = context_store
        self._context_repository = context_repository or MemoryContextRepository()
        self._context_persistence = ContextPersistence(
            context_store=self._context_store,
            context_repository=self._context_repository,
        )
        self._dashboard_services = dashboard_services
        self._llm_provider_factory = llm_provider_factory
        self._warehouse_repository = warehouse_repository
        self._code_tools_enabled = code_tools_enabled
        data_question_worker = (
            DataQuestionWorker(warehouse_repository)
            if warehouse_repository is not None
            else None
        )
        domain_cards = default_domain_agent_cards()
        tool_catalog = default_tool_catalog(
            warehouse_repository=warehouse_repository,
            dashboard_services=dashboard_services,
            firecrawl_adapter=firecrawl_adapter,
        )
        if code_tools_enabled:
            register_workspace_tools(tool_catalog, workspace_root or Path.cwd())
        self._worker_cards = default_worker_agent_cards()
        active_worker_cards = tuple(
            card
            for card in self._worker_cards
            if code_tools_enabled or card.domain != "code"
        )
        self._workspace_root_allowed_tool_names = tuple(
            dict.fromkeys(spec.tool_name for spec in tool_catalog.list_specs())
        )
        self._readonly_root_allowed_tool_names = tuple(
            dict.fromkeys(
                spec.tool_name
                for spec in tool_catalog.list_specs()
                if ToolPolicy.WORKSPACE_TOOLS not in spec.required_tool_policy
            )
        )
        self._workspace_root_allowed_artifact_types = tuple(
            dict.fromkeys(
                (
                    *_CONTROL_PLANE_ARTIFACT_TYPES,
                    *(
                        output
                        for card in active_worker_cards
                        for skill in card.skills
                        if not skill.planned_only
                        for output in skill.output_artifact_types
                    ),
                )
            )
        )
        self._readonly_root_allowed_artifact_types = tuple(
            dict.fromkeys(
                (
                    *_CONTROL_PLANE_ARTIFACT_TYPES,
                    *(
                        output
                        for card in self._worker_cards
                        if card.domain != "code"
                        for skill in card.skills
                        if not skill.planned_only
                        for output in skill.output_artifact_types
                    ),
                )
            )
        )
        self._executor_registry = _default_worker_executor_registry(
            data_question_worker=data_question_worker,
            llm_provider_factory=llm_provider_factory,
            tool_catalog=tool_catalog,
            worker_cards=self._worker_cards,
            code_tools_enabled=code_tools_enabled,
        )
        self._capability_registry = CapabilityRegistry(
            domain_cards=domain_cards,
            worker_cards=self._worker_cards,
            executor_registry=self._executor_registry,
            tool_catalog=tool_catalog,
            feature_flags={
                "code": code_tools_enabled,
                "data": warehouse_repository is not None,
            },
        )
        self._startup_contract_report = self._capability_registry.validate_startup_contracts()
        if not self._startup_contract_report.valid:
            raise AgentRuntimeUnavailableError(
                "Agent capability contract failed: "
                + ", ".join(self._startup_contract_report.errors)
            )
        self._capability_authority = CapabilityAuthority()
        self._tool_audit_store = tool_audit_store or InMemoryToolAuditStore()
        self._tool_gateway = ToolGateway(
            catalog=tool_catalog,
            audit_store=self._tool_audit_store,
            capability_authority=self._capability_authority,
        )
        # Resolve the planning LLM per construction so cache-clear rebuilds pick up
        # rotated provider secrets; workers still use the factory for later calls.
        planning_llm_provider = llm_provider_factory()
        self._main_runtime = main_runtime or MainRuntime(
            domain_cards=domain_cards,
            planner=LLMMainAgentPlanner(llm_provider=planning_llm_provider),
            capability_registry=self._capability_registry,
        )
        self._worker_runtime = WorkerRuntime(
            executor_registry=self._executor_registry
        )
        self._a2a_transport = InProcessA2ATransport()
        endpoint_domain_cards = tuple(
            card for card in domain_cards if code_tools_enabled or card.domain != "code"
        )
        endpoint_worker_cards = tuple(
            card for card in self._worker_cards if code_tools_enabled or card.domain != "code"
        )
        register_hierarchy_endpoints(
            transport=self._a2a_transport,
            domain_cards=endpoint_domain_cards,
            worker_cards=endpoint_worker_cards,
            expert_planner_factory=lambda: LLMExpertAgentPlanner(
                llm_provider=self._llm_provider_factory()
            ),
            capability_registry=self._capability_registry,
            capability_authority=self._capability_authority,
            worker_runtime=self._worker_runtime,
            context_store=self._context_store,
            context_repository=self._context_repository,
            tool_gateway=self._tool_gateway,
            tool_audit_store=self._tool_audit_store,
            llm_provider_factory=self._llm_provider_factory,
            expert_max_concurrency=expert_max_concurrency,
        )
        self._hierarchy = HierarchicalPlanExecutor(
            transport=self._a2a_transport,
            max_concurrency=main_max_concurrency,
        )
        self._audit_pipeline = audit_pipeline or AuditPipeline()

    def run_user_qna(self, command: UserQnaCommand) -> UserQnaRunResult:
        """Run one user Q&A request through v1 planning and final audit."""
        raw_guardrail = _evaluate_user_input(command.message)
        if not raw_guardrail.allowed:
            raise AgentInputBlockedError(raw_guardrail)
        command = _command_with_current_user_message(command)
        if command.resolved_turn_context is None:
            command = replace(
                command,
                resolved_turn_context=resolve_turn_context(command.message),
            )
        guardrail = _evaluate_user_input(command.message)
        if not guardrail.allowed:
            raise AgentInputBlockedError(guardrail)
        workspace_tools_allowed = (
            self._code_tools_enabled and command.allow_workspace_tools
        )

        self._context_store.add_run(
            AgentRun(
                run_id=command.run_id,
                run_type=AgentRunType.USER_QNA,
                status=RuntimeAgentExecutionStatus.RUNNING,
                permission_mode=(
                    AgentPermissionMode.WRITE_ALLOWED
                    if workspace_tools_allowed
                    else AgentPermissionMode.READ_ONLY
                ),
                trigger_source="user_qna",
                user_intent_summary=command.message,
                started_at=datetime.now(UTC),
            )
        )
        root_token = _root_capability_token(
            command.run_id,
            allow_workspace_tools=workspace_tools_allowed,
            allowed_tool_names=(
                self._workspace_root_allowed_tool_names
                if workspace_tools_allowed
                else self._readonly_root_allowed_tool_names
            ),
            allowed_artifact_types=(
                self._workspace_root_allowed_artifact_types
                if workspace_tools_allowed
                else self._readonly_root_allowed_artifact_types
            ),
        )
        self._capability_authority.issue(root_token)
        context_pack = self._build_and_store_context_pack(command, root_token)
        global_plan = self._main_runtime.create_global_plan(
            run_id=command.run_id,
            run_type="user_qna",
            user_goal=command.message,
            context_pack=context_pack,
            capability_token=root_token,
            conversation_context=tuple(command.conversation_context),
        )
        for token in self._main_runtime.issued_tokens.values():
            if token.run_id == command.run_id:
                self._capability_authority.issue(token)
        if not global_plan.domain_tasks:
            return self._blocked_run_result_from_planner_messages(
                command=command,
                guardrail=guardrail,
                global_plan=global_plan,
            )

        artifacts: list[ContextArtifact] = []
        available_artifacts: dict[str, ContextArtifact] = {}
        approved_capsule_refs: list[str] = []
        approved_evidence_refs: list[str] = []
        used_artifact_refs: list[str] = []
        trace_steps: list[AgentTraceStep] = []
        activities: list[AgentTraceActivity] = [
            AgentTraceActivity(
                activity_id=f"{command.run_id}:planning",
                stage="planning",
                actor="MainAgent",
                action="route_request",
                status=AgentExecutionStatus.SUCCEEDED,
                summary="已根据当前问题和结构化上下文生成执行计划。",
            )
        ]
        table_rows: list[dict[str, Any]] = []
        domain_answer_fragments: list[DomainAnswerFragment] = []

        hierarchy_result = self._hierarchy.execute(
            plan=global_plan,
            run_context=AgentRunContext(
                run_id=command.run_id,
                trigger="user_qna",
                goal=command.message,
                language=command.language,
                scope_version_id=command.scope_version_id,
                universe=command.universe,
                conversation_context=tuple(command.conversation_context),
                resolved_turn_context=command.resolved_turn_context,
            ),
            context_pack=context_pack,
        )
        task_by_id = {task.domain_task_id: task for task in global_plan.domain_tasks}
        for execution in hierarchy_result.domain_executions:
            domain_task = task_by_id[execution.result.domain_task_id]
            domain_capsule = execution.capsule
            domain_audit = execution.audit
            self._context_repository.save_domain_capsule(
                domain_capsule,
                domain_task_id=domain_task.domain_task_id,
                expert_agent=domain_task.to_domain_agent,
                output_artifact_refs=domain_capsule.artifact_refs,
                audit_report_ref=domain_audit.audit_report_id,
                token_estimate=len(domain_capsule.model_dump_json()),
            )
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=domain_capsule.capsule_id,
                to_ref=context_pack.context_pack_id,
                edge_type="source_ref",
            )
            for artifact_ref in domain_capsule.artifact_refs:
                self._context_repository.record_lineage_edge(
                    run_id=command.run_id,
                    from_ref=domain_capsule.capsule_id,
                    to_ref=artifact_ref,
                    edge_type="source_ref",
                )
            for evidence_ref in domain_capsule.evidence_refs:
                approved_evidence_refs.append(evidence_ref)
                self._context_repository.record_lineage_edge(
                    run_id=command.run_id,
                    from_ref=domain_capsule.capsule_id,
                    to_ref=evidence_ref,
                    edge_type="evidence_ref",
                )
            domain_artifacts = execution.artifacts
            artifacts.extend(domain_artifacts)
            available_artifacts.update(
                {artifact.artifact_id: artifact for artifact in domain_artifacts}
            )
            approved_capsule_refs.append(domain_capsule.capsule_id)
            domain_answer_fragments.append(
                DomainAnswerFragment(
                    domain_agent=domain_task.to_domain_agent,
                    domain=domain_task.domain,
                    answer=execution.answer,
                    capsule_ref=domain_capsule.capsule_id,
                    status=execution.result.status,
                )
            )
            used_artifact_refs.extend(
                artifact.artifact_id for artifact in execution.artifacts
            )
            table_rows.extend(execution.table_rows)
            reviewed_worker = execution.worker_results[-1] if execution.worker_results else None
            trace_steps.append(
                AgentTraceStep(
                    step_id=domain_task.domain_task_id,
                    expert_agent_name=domain_task.to_domain_agent,
                    skill_id=(reviewed_worker.skill_id if reviewed_worker else "expert_review"),
                    status=execution.result.status,
                )
            )
            activities.append(
                _safe_trace_activity(
                    activity_id=f"{command.run_id}:{domain_task.domain_task_id}",
                    actor=domain_task.to_domain_agent,
                    action=(
                        reviewed_worker.skill_id
                        if reviewed_worker is not None
                        else "review_result"
                    ),
                    status=execution.result.status,
                    has_missing_requirements=bool(
                        execution.result.missing_requirements
                    ),
                    evidence_refs=tuple(domain_capsule.evidence_refs),
                )
            )

        answer = _synthesize_domain_answer_fragments(domain_answer_fragments)
        answer, writing_artifact = _writing_revision_artifact(
            run_id=command.run_id,
            answer=answer,
            language=command.language,
            used_domain_capsule_refs=tuple(approved_capsule_refs),
        )
        artifacts.append(writing_artifact)
        available_artifacts[writing_artifact.artifact_id] = writing_artifact
        used_artifact_refs.append(writing_artifact.artifact_id)

        final_audit = self._audit_pipeline.audit_final_answer(
            run_id=command.run_id,
            required_artifact_refs=tuple(approved_capsule_refs),
            available_artifacts=available_artifacts,
            approved_capsule_refs=tuple(approved_capsule_refs),
            evidence_refs=tuple(dict.fromkeys(approved_evidence_refs)),
        )
        final_answer = FinalUserAnswerArtifact(
            artifact_id=f"fua_{command.run_id}",
            run_id=command.run_id,
            answer_text=answer,
            language=command.language,
            used_domain_capsule_refs=tuple(approved_capsule_refs),
            used_artifact_refs=tuple(dict.fromkeys(used_artifact_refs)),
            evidence_refs=tuple(dict.fromkeys(approved_evidence_refs)),
            source_refs=("agent:v1:user_qna",),
            disclaimers=("research_support_not_financial_advice",),
            limitations=("offline_research_context_may_be_incomplete",),
            final_audit_report_ref=final_audit.audit_report_id,
        )
        final_answer_artifact = make_context_artifact(
            artifact_id=final_answer.artifact_id,
            run_id=command.run_id,
            artifact_type="final_user_answer",
            producer_agent="MainAgent",
            payload_json=final_answer.model_dump(mode="json"),
            source_refs=final_answer.source_refs,
            evidence_refs=final_answer.evidence_refs,
        )
        final_audit_artifact = make_context_artifact(
            artifact_id=final_audit.audit_report_id,
            run_id=command.run_id,
            artifact_type="final_audit_report",
            producer_agent="MainAgent",
            payload_json=final_audit.model_dump(mode="json"),
            source_refs=("agent:v1:user_qna",),
            evidence_refs=final_audit.evidence_refs,
        )
        artifacts.extend((final_audit_artifact, final_answer_artifact))
        for artifact in artifacts:
            self._context_store.add_artifact(artifact)
        return UserQnaRunResult(
            answer=answer,
            guardrail=guardrail,
            global_plan=global_plan,
            trace_steps=tuple(trace_steps),
            artifacts=tuple(artifacts),
            references=_references_from_rows(
                table_rows,
                evidence_refs=tuple(dict.fromkeys(approved_evidence_refs)),
            ),
            final_answer=final_answer,
            activities=tuple(activities),
        )

    def get_context_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return a context artifact for scoped frontend expansion.

        Structured ContextPacks are owned by ContextRepository and reconstructed
        on demand when the runtime artifact table has no row.
        """
        return self._context_persistence.get_runtime_artifact(artifact_id)

    def _blocked_run_result_from_planner_messages(
        self,
        *,
        command: UserQnaCommand,
        guardrail: GuardrailSummary,
        global_plan: GlobalPlan,
    ) -> UserQnaRunResult:
        """Return a structured blocked answer when planning produces no executable tasks."""
        answer = _planner_messages_answer(global_plan.planner_messages)
        answer, writing_artifact = _writing_revision_artifact(
            run_id=command.run_id,
            answer=answer,
            language=command.language,
            used_domain_capsule_refs=(),
        )
        final_audit = self._audit_pipeline.audit_final_answer(
            run_id=command.run_id,
            required_artifact_refs=(),
            available_artifacts={writing_artifact.artifact_id: writing_artifact},
            approved_capsule_refs=(),
        )
        final_answer = FinalUserAnswerArtifact(
            artifact_id=f"fua_{command.run_id}",
            run_id=command.run_id,
            answer_text=answer,
            language=command.language,
            used_domain_capsule_refs=(),
            used_artifact_refs=(writing_artifact.artifact_id,),
            source_refs=("agent:v1:user_qna",),
            disclaimers=("research_support_not_financial_advice",),
            limitations=("requested_capability_not_executable",),
            final_audit_report_ref=final_audit.audit_report_id,
        )
        final_audit_artifact = make_context_artifact(
            artifact_id=final_audit.audit_report_id,
            run_id=command.run_id,
            artifact_type="final_audit_report",
            producer_agent="MainAgent",
            payload_json=final_audit.model_dump(mode="json"),
            source_refs=("agent:v1:user_qna",),
        )
        final_answer_artifact = make_context_artifact(
            artifact_id=final_answer.artifact_id,
            run_id=command.run_id,
            artifact_type="final_user_answer",
            producer_agent="MainAgent",
            payload_json=final_answer.model_dump(mode="json"),
            source_refs=final_answer.source_refs,
        )
        artifacts = (writing_artifact, final_audit_artifact, final_answer_artifact)
        for artifact in artifacts:
            self._context_store.add_artifact(artifact)
        return UserQnaRunResult(
            answer=answer,
            guardrail=guardrail,
            global_plan=global_plan,
            trace_steps=(),
            artifacts=artifacts,
            references=(),
            final_answer=final_answer,
            activities=(
                AgentTraceActivity(
                    activity_id=f"{command.run_id}:planning",
                    stage="planning",
                    actor="MainAgent",
                    action="route_request",
                    status=AgentExecutionStatus.BLOCKED,
                    summary=(
                        "规划阶段未找到可验证的执行路径；详细诊断已保留在审计记录中。"
                    ),
                ),
            ),
        )

    def _build_and_store_context_pack(
        self,
        command: UserQnaCommand,
        capability_token: CapabilityToken | None = None,
    ) -> ContextPack:
        """Build and persist the L1 ContextPack via the unified write path."""
        readiness_artifact = DataReadinessBuilder(
            dashboard_services=self._dashboard_services,
            warehouse_repository=self._warehouse_repository,
            capability_registry=self._capability_registry,
            capability_token=capability_token,
        ).build_for_user_qna(command)
        context_pack = ContextRouter().build_context_pack(
            run_id=command.run_id,
            requester_agent="MainAgent",
            target_agent="MainAgent",
            purpose="user_qna_planning",
            token_budget=4000,
            artifacts=(readiness_artifact,),
            included_chat_summary_ref=f"chat_summary:{_conversation_hash(command)}",
            resolved_turn_context=command.resolved_turn_context,
        )
        return self._context_persistence.persist_context_pack(
            context_pack,
            readiness_artifact=readiness_artifact,
        )


def _default_worker_executor_registry(
    *,
    data_question_worker: DataQuestionWorker | None,
    llm_provider_factory: Callable[[], LLMProvider],
    tool_catalog: Any,
    worker_cards: tuple[Any, ...],
    code_tools_enabled: bool,
) -> ExecutorRegistry:
    """Return default WorkerAgent executors for the v1 user-Q&A service."""
    registry = ExecutorRegistry()
    skill_by_key = {
        (card.name, skill.skill_id): skill
        for card in worker_cards
        for skill in card.skills
        if not skill.planned_only
    }
    data_skill = skill_by_key[("DataQuestionWorker", "answer_financial_metric")]
    registry.register_spec(
        ExecutorSpec(
            agent_name="DataQuestionWorker",
            skill_id="answer_financial_metric",
            executor=DataQuestionWorkerExecutor(data_question_worker),
            runtime="langgraph",
            required_tools=data_skill.tool_allowlist,
            output_artifact_types=data_skill.output_artifact_types,
            domain="data",
        )
    )
    general_skill = skill_by_key[("GeneralQnaWorker", "answer_general_qna")]
    registry.register_spec(
        ExecutorSpec(
            agent_name="GeneralQnaWorker",
            skill_id="answer_general_qna",
            executor=GeneralQnaWorkerExecutor(
                llm_provider_factory=llm_provider_factory,
            ),
            runtime="langgraph",
            required_tools=general_skill.tool_allowlist,
            output_artifact_types=general_skill.output_artifact_types,
            domain="general",
        )
    )
    if code_tools_enabled:
        code_skill = skill_by_key[("CodeWorkspaceWorker", "complete_code_task")]
        registry.register_spec(
            ExecutorSpec(
                agent_name="CodeWorkspaceWorker",
                skill_id="complete_code_task",
                executor=LangGraphWorkerExecutor(
                    tool_catalog=tool_catalog,
                    minimum_tool_calls=int(
                        code_skill.input_contract.get("minimum_tool_calls", 0)
                    ),
                    artifact_tool_requirements=_artifact_tool_requirements(
                        code_skill.tool_contracts
                    ),
                ),
                runtime="langgraph",
                required_tools=code_skill.tool_allowlist,
                output_artifact_types=code_skill.output_artifact_types,
                domain="code",
            )
        )
    return registry


def _artifact_tool_requirements(
    contracts: tuple[dict[str, Any], ...],
) -> dict[str, tuple[str, ...]]:
    requirements: dict[str, list[str]] = {}
    for contract in contracts:
        tool_name = str(contract.get("tool_name") or "")
        outputs = contract.get("produces", ())
        if not tool_name or not isinstance(outputs, list | tuple):
            continue
        for output in outputs:
            requirements.setdefault(str(output), []).append(tool_name)
    return {output: tuple(tool_names) for output, tool_names in requirements.items()}


def _safe_trace_activity(
    *,
    activity_id: str,
    actor: str,
    action: str,
    status: AgentExecutionStatus,
    has_missing_requirements: bool,
    evidence_refs: tuple[str, ...],
) -> AgentTraceActivity:
    """Build a bounded activity record without model reasoning or raw errors."""
    return AgentTraceActivity(
        activity_id=activity_id,
        stage="validation" if has_missing_requirements else "execution",
        actor=actor,
        action=action,
        status=status,
        summary=(
            "该步骤未产出完整的可验证结果；详细诊断已保留在审计记录中。"
            if has_missing_requirements
            else "该步骤已完成并通过结构化校验。"
            if status is AgentExecutionStatus.SUCCEEDED
            else "该步骤未完成；可重试状态已记录在执行活动中。"
        ),
        evidence_refs=evidence_refs,
    )


def _synthesize_domain_answer_fragments(
    fragments: list[DomainAnswerFragment],
) -> str:
    """Synthesize final answer text from approved domain fragments."""
    if not fragments:
        raise AgentRuntimeUnavailableError("No domain answer fragments available")
    completed_answers = tuple(
        dict.fromkeys(
            safe_answer
            for fragment in fragments
            if fragment.status
            in {AgentExecutionStatus.SUCCEEDED, AgentExecutionStatus.PARTIAL}
            and (safe_answer := _public_safe_message(fragment.answer))
        )
    )
    if len(completed_answers) == 1:
        return completed_answers[0]
    if completed_answers:
        return "\n\n".join(("### 综合回答", *completed_answers))
    return (
        "### 暂时无法完成\n\n"
        "当前查询尚未得到可验证结果。请确认查询对象、指标和时间范围，或稍后重试。"
    )


def _planner_messages_answer(messages: tuple[dict[str, Any], ...]) -> str:
    """Return a concise blocked answer from non-executable MainAgent plan messages."""
    details = []
    for message in messages:
        text = _public_safe_message(
            message.get("user_safe_message")
            or message.get("reason")
            or "当前能力不可执行。"
        )
        if text:
            details.append(text)
    if not details:
        details.append("当前环境暂时无法完成这项查询。")
    lines = ["### 暂时无法完成", *[f"- {detail}" for detail in dict.fromkeys(details)]]
    lines.extend(
        [
            "### 下一步",
            "- 请补充查询对象、指标和时间范围，或稍后重试。",
        ]
    )
    return "\n\n".join(lines)


_INTERNAL_RUNTIME_TERM_RE = re.compile(
    r"(?i)\b(?:worker|tool|repository|executor|artifact)s?\b|"
    r"missing\s+(?:required\s+)?artifacts?|依赖(?:任务|步骤)?|跳过依赖|"
    r"前置\s*agent|agent\s+(?:capability|execution)"
)


def _public_safe_message(value: object) -> str:
    """Return user-facing text only when it contains no runtime diagnostics."""
    text = strip_thinking_blocks(str(value or "")).strip()
    if not text or _INTERNAL_RUNTIME_TERM_RE.search(text):
        return ""
    return text


def _command_with_current_user_message(command: UserQnaCommand) -> UserQnaCommand:
    """Return a command whose message is only the current user turn."""
    current_message = _current_user_message_text(command.message, max_chars=2000)
    if not current_message or current_message == command.message:
        return command
    return replace(command, message=current_message)


def _current_user_message_text(value: object, *, max_chars: int) -> str:
    """Extract the active user turn from possible role-marked transcripts."""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?i)\bcurrent_user\s*:\s*", text)
    if len(parts) > 1:
        text = parts[-1]
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"(?i)^(?:assistant|system)\s*:", line):
            continue
        line = re.sub(r"(?i)^(?:user|current_user)\s*:\s*", "", line).strip()
        if line:
            lines.append(line)
    compact = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return compact[:max_chars].strip()


def _worker_task_goal(
    *,
    user_message: str,
    conversation_context: tuple[dict[str, str], ...],
    expert_task: str,
    worker_task: str,
    worker_inputs: object | None = None,
) -> str:
    """Build the WorkerAgent task prompt without echoing assistant transcripts.

    Data workers must receive the current user turn as the authoritative lookup
    input.  Previous assistant answers often contain formatted no-data messages;
    copying them into task_goal caused downstream tools to treat a whole chat
    transcript as a security name.
    """
    recent_user_turns = "\n".join(
        f"user: {_prompt_safe_text(item.get('content', ''), max_chars=180)}"
        for item in conversation_context[-6:]
        if item.get("role") == "user" and item.get("content")
    )
    return "\n".join(
        item
        for item in (
            f"expert_task: {_prompt_safe_text(expert_task, max_chars=360)}",
            f"worker_task: {_prompt_safe_text(worker_task, max_chars=360)}",
            f"worker_inputs: {_prompt_safe_text(repr(worker_inputs), max_chars=360)}"
            if worker_inputs is not None
            else "",
            "recent_user_turns:" if recent_user_turns else "",
            recent_user_turns,
            f"current_user: {_prompt_safe_text(user_message, max_chars=300)}",
        )
        if item
    )


def _prompt_safe_text(value: object, *, max_chars: int) -> str:
    """Return compact single-line text for runtime prompts."""
    text = str(value or "")
    parts = re.split(r"(?i)\bcurrent_user\s*:\s*", text)
    if len(parts) > 1:
        text = parts[-1]
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].strip()


def _writing_revision_artifact(
    *,
    run_id: str,
    answer: str,
    language: str,
    used_domain_capsule_refs: tuple[str, ...],
) -> tuple[str, ContextArtifact]:
    """Return a WritingAgent Markdown revision without changing facts."""
    markdown_answer = _format_answer_markdown(answer)
    artifact = make_context_artifact(
        artifact_id=f"ctx_{run_id}_writing_revision",
        run_id=run_id,
        artifact_type="writing_revision",
        producer_agent="WritingAgent",
        payload_json={
            "input_format": "plain_or_markdown",
            "output_format": "markdown",
            "language": language,
            "markdown_answer": markdown_answer,
            "rules": [
                "preserve_facts",
                "do_not_add_claims",
                "do_not_change_conclusion",
                "no_investment_advice",
            ],
            "used_domain_capsule_refs": list(used_domain_capsule_refs),
        },
        source_refs=(
            "agent:WritingAgent",
            *(f"domain_capsule:{ref}" for ref in used_domain_capsule_refs),
        ),
    )
    return markdown_answer, artifact


def _format_answer_markdown(answer: str) -> str:
    """Format a final answer as readable Markdown while preserving content."""
    clean = strip_thinking_blocks(answer).strip()
    if not clean or _looks_like_markdown(clean):
        return clean
    if len(clean) <= 28 and not re.search(r"[。！？!?].+", clean):
        return clean
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])\s*", clean)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return clean
    return "### 回答\n\n" + "\n".join(f"- {sentence}" for sentence in sentences)


def _looks_like_markdown(value: str) -> bool:
    """Return whether the answer already has explicit Markdown structure."""
    stripped = value.lstrip()
    return stripped.startswith(("#", "-", "*", "1.", "|", "```"))


def _artifact_id_part(value: str) -> str:
    """Return a stable artifact id fragment."""
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "agent"


def _root_capability_token(
    run_id: str,
    *,
    allow_workspace_tools: bool = False,
    allowed_tool_names: tuple[str, ...],
    allowed_artifact_types: tuple[str, ...],
) -> CapabilityToken:
    """Create the L1 root capability token for one user Q&A run."""
    return CapabilityToken(
        token_id=f"cap_{run_id}_root",
        run_id=run_id,
        issued_by="system",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_ANALYSIS_MART,
            DataAccessPolicy.READ_EVIDENCE,
            DataAccessPolicy.READ_PROVIDER_STATUS,
            *((DataAccessPolicy.READ_WORKSPACE,) if allow_workspace_tools else ()),
        ),
        production_write=(
            ProductionWritePolicy.WRITE_CONTEXT_ONLY,
            *(
                (ProductionWritePolicy.WRITE_WORKSPACE,)
                if allow_workspace_tools
                else ()
            ),
        ),
        tool_policy=(
            ToolPolicy.READ_ONLY_TOOLS,
            ToolPolicy.RETRIEVAL_TOOLS,
            ToolPolicy.QUANT_TOOLS,
            ToolPolicy.DATA_SYNC_TOOLS,
            *((ToolPolicy.WORKSPACE_TOOLS,) if allow_workspace_tools else ()),
        ),
        allowed_artifact_types=allowed_artifact_types,
        allowed_tool_names=allowed_tool_names,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=32,
        max_result_bytes=1_000_000 if allow_workspace_tools else 64_000,
        can_delegate=True,
        delegation_depth_remaining=2,
    )


def _evaluate_user_input(message: str) -> GuardrailSummary:
    """Run deterministic v1 input guardrails."""
    normalized = message.lower()
    policies: list[str] = []
    if _has_financial_guarantee(normalized):
        policies.append("financial_guarantee")
    if any(
        term in normalized
        for term in (
            "忽略系统规则",
            "忽略之前",
            "忽略以上",
            "hidden tool",
            "system prompt",
            "开发者消息",
        )
    ):
        policies.append("prompt_injection")
    if policies:
        return GuardrailSummary(
            allowed=False,
            decision="deny",
            summary="不能保证收益。系统只能展示研究判断、证据、风险和不确定性。",
            triggered_policies=tuple(policies),
        )
    return GuardrailSummary(
        allowed=True,
        decision="allow",
        summary="input allowed",
    )


def _has_financial_guarantee(normalized_input: str) -> bool:
    """Return whether the user asks for a guaranteed financial outcome."""
    guarantee_terms = (
        "保证收益",
        "稳赚",
        "保本",
        "确定上涨",
        "必涨",
        "guaranteed return",
        "guaranteed profit",
    )
    if any(term in normalized_input for term in guarantee_terms):
        return True
    return any(term in normalized_input for term in ("保证", "保證")) and any(
        term in normalized_input for term in ("收益", "盈利", "赚钱", "回报", "利潤", "利润")
    )


def _build_user_answer_prompt(
    *,
    command: UserQnaCommand,
    context_pack: ContextPack,
    table_rows: list[dict[str, Any]],
) -> str:
    """Build the final-answer prompt from bounded context."""
    chat_context = "\n".join(
        f"- {item.get('role', 'unknown')}: {item.get('content', '')[:500]}"
        for item in command.conversation_context[-8:]
    )
    rows = "\n".join(
        (
            f"- {row['security_id']}: score={row.get('final_score')}, "
            f"confidence={row.get('confidence')}, status={row.get('screening_status')}"
        )
        for row in table_rows[:10]
    )
    rows = rows or "- 当前 dashboard 候选为空或不可用。"
    return "\n".join(
        [
            "你是 Margin 的本地投研助手，只能基于给定上下文回答。",
            "禁止给出投资建议口吻，禁止使用买入、卖出、持有等指令性表达。",
            f"语言: {command.language}",
            f"ContextPack: {context_pack.context_pack_id}",
            f"用户问题: {command.message}",
            "最近对话摘要:",
            chat_context or "- 无",
            "Dashboard 研究候选摘要:",
            rows,
            "请输出 Markdown：先给直接回答，再用简短要点说明依据和不确定性。",
        ]
    )


def _references_from_rows(
    rows: list[dict[str, Any]],
    *,
    evidence_refs: tuple[str, ...] = (),
) -> tuple[dict[str, str], ...]:
    """Return safe frontend references for warehouse rows and RAG evidence artifacts."""
    references: list[dict[str, str]] = []
    for row in rows[:10]:
        security_id = str(row.get("security_id") or "")
        indicator_id = str(row.get("indicator_id") or "")
        fact_id = str(row.get("fact_id") or "")
        if indicator_id and row.get("date") and row.get("source"):
            locator = str(
                row.get("locator")
                or (
                    "warehouse://indicator-history/"
                    f"{security_id}/{indicator_id}/{fact_id or row['date']}"
                )
            )
            reference = {
                    "type": "warehouse_fact",
                    "source_kind": "warehouse_fact",
                    "id": fact_id or locator,
                    "label": (
                        f"{security_id} {row.get('metric') or indicator_id} {row['date']}"
                    ),
                    "security_id": security_id,
                    "indicator": indicator_id,
                    "indicator_id": indicator_id,
                    "date": str(row["date"]),
                    "source": str(row["source"]),
                    "source_name": str(row["source"]),
                    "source_level": "L3",
                    "fact_id": fact_id,
                    "locator": locator,
                    "snapshot_id": str(row.get("raw_snapshot_id") or ""),
                    "pit_timestamp": str(row.get("available_at") or ""),
                }
            if fact_id:
                reference.update(
                    {
                        "evidence_id": fact_id,
                        "detail_url": f"/api/v1/evidence/{fact_id}",
                    }
                )
            references.append(reference)
            continue
        if security_id:
            references.append(
                {
                    "type": "dashboard_candidate",
                    "id": security_id,
                    "label": security_id,
                }
            )
    existing_ids = {item.get("evidence_id") or item.get("id") for item in references}
    for raw_ref in evidence_refs:
        evidence_id = _canonical_evidence_id(raw_ref)
        if not evidence_id or evidence_id in existing_ids:
            continue
        references.append(
            {
                "type": "document_evidence",
                "source_kind": "document",
                "id": evidence_id,
                "evidence_id": evidence_id,
                "detail_url": f"/api/v1/evidence/{evidence_id}",
                "label": evidence_id,
                "locator": f"evidence_id:{evidence_id}",
            }
        )
        existing_ids.add(evidence_id)
    return tuple(references)


def _canonical_evidence_id(reference: str) -> str:
    """Normalize an artifact evidence reference into the canonical detail ID."""
    value = str(reference or "").strip()
    if value.startswith("evidence://"):
        return value.removeprefix("evidence://").strip("/")
    if value.startswith("evidence:"):
        return value.removeprefix("evidence:").strip()
    return value


def _conversation_hash(command: UserQnaCommand) -> str:
    """Return a stable short hash for the conversation summary reference."""
    raw = "|".join(
        f"{item.get('role', '')}:{item.get('content', '')}"
        for item in command.conversation_context
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
