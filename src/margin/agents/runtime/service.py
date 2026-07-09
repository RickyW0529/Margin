"""Application-facing v1 Agent runtime service."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
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
from margin.agents.cards.registry import default_domain_agent_cards, default_worker_agent_cards
from margin.agents.context.readiness_builder import DataReadinessBuilder
from margin.agents.context.repository import ContextRepository, MemoryContextRepository
from margin.agents.context.router import ContextRouter
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    DomainAuditReport,
    DomainContextCapsule,
    FinalUserAnswerArtifact,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.protocol.planning import PlanActionKind
from margin.agents.runtime.audit_pipeline import AuditPipeline
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.domain_runtime import DomainRuntime
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
)
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.runtime.expert_runtime import LLMExpertAgentPlanner, WorkerPlanStepDraft
from margin.agents.runtime.main_runtime import GlobalPlan, LLMMainAgentPlanner, MainRuntime
from margin.agents.runtime.worker_executors import (
    DataQuestionWorkerExecutor,
    GeneralQnaWorkerExecutor,
)
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import default_tool_catalog
from margin.agents.tools.gateway import ToolGateway
from margin.agents.workers.data_question_worker import DataQuestionWorker
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import LLMProvider, strip_thinking_blocks

USER_QNA_RUNTIME_VERSION = "agent-runtime-v1-user-qna"
_DEFAULT_ALLOWED_ARTIFACT_TYPES = (
    "analysis_table",
    "chart_spec",
    "computed_metric",
    "data_context_capsule",
    "data_readiness",
    "domain_audit_report",
    "domain_context_capsule",
    "evidence_context_capsule",
    "evidence_package",
    "explanation",
    "final_audit_report",
    "final_user_answer",
    "qna_answer",
    "quant_context_capsule",
    "quant_result",
    "stock_research_context_capsule",
    "visualization_image",
    "writing_revision",
    "worker_activity",
)
_DATA_QUESTION_TOOL_ALLOWLIST = (
    "warehouse.describe_schema",
    "warehouse.resolve_security",
    "warehouse.discover_indicators",
    "warehouse.query_indicator_history",
)
_DATA_QUESTION_OUTPUT_TYPES = (
    "analysis_table",
    "chart_spec",
    "computed_metric",
    "qna_answer",
    "visualization_image",
    "worker_activity",
)
_GENERAL_QNA_OUTPUT_TYPES = ("analysis_table", "qna_answer")


@dataclass(frozen=True)
class UserQnaCommand:
    """One user-facing Q&A command entering the v1 runtime."""

    run_id: str
    scope_version_id: str
    message: str
    universe: str
    language: Literal["zh", "en"]
    conversation_context: Sequence[dict[str, str]] = ()


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
    ) -> None:
        """Initialize the application-facing v1 Agent runtime service."""
        self._context_store = context_store
        self._context_repository = context_repository or MemoryContextRepository()
        self._dashboard_services = dashboard_services
        self._llm_provider_factory = llm_provider_factory
        self._warehouse_repository = warehouse_repository
        data_question_worker = (
            DataQuestionWorker(warehouse_repository)
            if warehouse_repository is not None
            else None
        )
        planning_llm_provider = llm_provider_factory()
        domain_cards = default_domain_agent_cards()
        tool_catalog = default_tool_catalog(
            warehouse_repository=warehouse_repository,
            dashboard_services=dashboard_services,
        )
        self._expert_planner = LLMExpertAgentPlanner(llm_provider=planning_llm_provider)
        self._worker_cards = default_worker_agent_cards()
        self._executor_registry = _default_worker_executor_registry(
            data_question_worker=data_question_worker,
            dashboard_services=dashboard_services,
            llm_provider_factory=llm_provider_factory,
        )
        self._capability_registry = CapabilityRegistry(
            domain_cards=domain_cards,
            worker_cards=self._worker_cards,
            executor_registry=self._executor_registry,
            tool_catalog=tool_catalog,
        )
        self._startup_contract_report = self._capability_registry.validate_startup_contracts()
        self._tool_gateway = ToolGateway(
            catalog=tool_catalog,
            audit_store=InMemoryToolAuditStore(),
        )
        self._main_runtime = main_runtime or MainRuntime(
            domain_cards=domain_cards,
            planner=LLMMainAgentPlanner(llm_provider=planning_llm_provider),
            capability_registry=self._capability_registry,
        )
        self._worker_runtime = WorkerRuntime(
            executor_registry=self._executor_registry
        )
        self._audit_pipeline = audit_pipeline or AuditPipeline()

    def run_user_qna(self, command: UserQnaCommand) -> UserQnaRunResult:
        """Run one user Q&A request through v1 planning and final audit."""
        raw_guardrail = _evaluate_user_input(command.message)
        if not raw_guardrail.allowed:
            raise AgentInputBlockedError(raw_guardrail)
        command = _command_with_current_user_message(command)
        guardrail = _evaluate_user_input(command.message)
        if not guardrail.allowed:
            raise AgentInputBlockedError(guardrail)

        self._context_store.add_run(
            AgentRun(
                run_id=command.run_id,
                run_type=AgentRunType.USER_QNA,
                status=RuntimeAgentExecutionStatus.RUNNING,
                permission_mode=AgentPermissionMode.READ_ONLY,
                trigger_source="user_qna",
                user_intent_summary=command.message,
                started_at=datetime.now(UTC),
            )
        )
        root_token = _root_capability_token(command.run_id)
        context_pack = self._build_and_store_context_pack(command, root_token)
        global_plan = self._main_runtime.create_global_plan(
            run_id=command.run_id,
            run_type="user_qna",
            user_goal=command.message,
            context_pack=context_pack,
            capability_token=root_token,
            conversation_context=tuple(command.conversation_context),
        )
        if not global_plan.domain_tasks:
            return self._blocked_run_result_from_planner_messages(
                command=command,
                guardrail=guardrail,
                global_plan=global_plan,
            )

        artifacts: list[ContextArtifact] = []
        available_artifacts: dict[str, ContextArtifact] = {}
        approved_capsule_refs: list[str] = []
        used_artifact_refs: list[str] = []
        trace_steps: list[AgentTraceStep] = []
        table_rows: list[dict[str, Any]] = []
        domain_answer_fragments: list[DomainAnswerFragment] = []

        for domain_task in global_plan.domain_tasks:
            execution = self._execute_domain_task(
                command=command,
                context_pack=context_pack,
                domain_task=domain_task,
            )
            if execution.result.status not in {
                AgentExecutionStatus.SUCCEEDED,
                AgentExecutionStatus.PARTIAL,
                AgentExecutionStatus.BLOCKED,
            }:
                raise AgentRuntimeUnavailableError("Worker did not produce a user-safe answer")
            table_artifact = _first_artifact_of_type(execution.artifacts, "analysis_table")
            if table_artifact is None:
                table_artifact = _empty_analysis_table_artifact(
                    command.run_id,
                    suffix=domain_task.domain,
                )
            answer_artifact = _first_artifact_of_type(execution.artifacts, "qna_answer")
            domain_answer = execution.answer or (
                answer_artifact.payload_json.get("answer", "") if answer_artifact else ""
            )
            if execution.result.status is not AgentExecutionStatus.SUCCEEDED:
                domain_answer = execution.result.safe_summary
            if not domain_answer:
                raise AgentRuntimeUnavailableError("Worker did not produce a user-safe answer")
            if answer_artifact is None:
                answer_artifact = _qna_answer_artifact(
                    run_id=command.run_id,
                    answer=domain_answer,
                    language=command.language,
                    producer_agent=execution.result.worker_agent,
                )
            extra_artifacts = tuple(
                artifact
                for artifact in execution.artifacts
                if artifact.artifact_id
                not in {table_artifact.artifact_id, answer_artifact.artifact_id}
            )
            table_rows.extend(execution.table_rows)
            domain_artifact_refs = (
                table_artifact.artifact_id,
                *(artifact.artifact_id for artifact in extra_artifacts),
                answer_artifact.artifact_id,
            )
            domain_capsule = DomainContextCapsule(
                capsule_id=f"dcc_{command.run_id}_{domain_task.domain}",
                run_id=command.run_id,
                domain=domain_task.domain,
                purpose="user_qna",
                status=execution.result.status,
                summary=domain_answer,
                artifact_refs=domain_artifact_refs,
                source_refs=("agent:v1:user_qna",),
                compression_policy_version="domain-capsule-v1",
                input_hash=context_pack.payload_hash,
            )
            domain_audit = DomainAuditReport(
                audit_report_id=f"da_{command.run_id}_{domain_task.domain}",
                run_id=command.run_id,
                domain_task_id=domain_task.domain_task_id,
                domain=domain_task.domain,
                status=execution.result.status,
                checked_artifact_refs=domain_artifact_refs,
                schema_valid=execution.result.status is AgentExecutionStatus.SUCCEEDED,
                evidence_valid=execution.result.status is AgentExecutionStatus.SUCCEEDED,
                source_refs_valid=True,
                context_budget_ok=True,
                safe_summary=(
                    "domain audit passed"
                    if execution.result.status is AgentExecutionStatus.SUCCEEDED
                    else execution.result.safe_summary
                ),
            )
            capsule_artifact = make_context_artifact(
                artifact_id=domain_capsule.capsule_id,
                run_id=command.run_id,
                artifact_type="domain_context_capsule",
                producer_agent=domain_task.to_domain_agent,
                payload_json=domain_capsule.model_dump(mode="json"),
                source_refs=domain_capsule.source_refs,
            )
            domain_audit_artifact = make_context_artifact(
                artifact_id=domain_audit.audit_report_id,
                run_id=command.run_id,
                artifact_type="domain_audit_report",
                producer_agent=domain_task.to_domain_agent,
                payload_json=domain_audit.model_dump(mode="json"),
                source_refs=("agent:v1:user_qna",),
            )
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
                self._context_repository.record_lineage_edge(
                    run_id=command.run_id,
                    from_ref=domain_capsule.capsule_id,
                    to_ref=evidence_ref,
                    edge_type="evidence_ref",
                )
            domain_artifacts = (
                table_artifact,
                *extra_artifacts,
                answer_artifact,
                capsule_artifact,
                domain_audit_artifact,
            )
            artifacts.extend(domain_artifacts)
            available_artifacts.update(
                {artifact.artifact_id: artifact for artifact in domain_artifacts}
            )
            approved_capsule_refs.append(domain_capsule.capsule_id)
            domain_answer_fragments.append(
                DomainAnswerFragment(
                    domain_agent=domain_task.to_domain_agent,
                    domain=domain_task.domain,
                    answer=domain_answer,
                    capsule_ref=domain_capsule.capsule_id,
                    status=execution.result.status,
                )
            )
            used_artifact_refs.extend(domain_artifact_refs)
            trace_steps.append(
                AgentTraceStep(
                    step_id=domain_task.domain_task_id,
                    expert_agent_name=domain_task.to_domain_agent,
                    skill_id=execution.result.skill_id,
                    status=execution.result.status,
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
        )
        final_answer = FinalUserAnswerArtifact(
            artifact_id=f"fua_{command.run_id}",
            run_id=command.run_id,
            answer_text=answer,
            language=command.language,
            used_domain_capsule_refs=tuple(approved_capsule_refs),
            used_artifact_refs=tuple(dict.fromkeys(used_artifact_refs)),
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
        )
        final_audit_artifact = make_context_artifact(
            artifact_id=final_audit.audit_report_id,
            run_id=command.run_id,
            artifact_type="final_audit_report",
            producer_agent="MainAgent",
            payload_json=final_audit.model_dump(mode="json"),
            source_refs=("agent:v1:user_qna",),
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
            references=_references_from_rows(table_rows),
            final_answer=final_answer,
        )

    def get_context_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return a context artifact for scoped frontend expansion."""
        return self._context_store.get_artifact(artifact_id)

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
        )

    def _build_and_store_context_pack(
        self,
        command: UserQnaCommand,
        capability_token: CapabilityToken | None = None,
    ) -> ContextPack:
        """Build and persist the L1 ContextPack artifact."""
        readiness_artifact = DataReadinessBuilder(
            dashboard_services=self._dashboard_services,
            warehouse_repository=self._warehouse_repository,
            capability_registry=self._capability_registry,
            capability_token=capability_token,
        ).build_for_user_qna(command)
        self._context_store.add_artifact(readiness_artifact)
        context_pack = ContextRouter().build_context_pack(
            run_id=command.run_id,
            requester_agent="MainAgent",
            target_agent="MainAgent",
            purpose="user_qna_planning",
            token_budget=4000,
            artifacts=(readiness_artifact,),
            included_chat_summary_ref=f"chat_summary:{_conversation_hash(command)}",
        )
        self._context_store.add_artifact(
            make_context_artifact(
                artifact_id=context_pack.context_pack_id,
                run_id=command.run_id,
                artifact_type="context_pack",
                producer_agent="MainAgent",
                payload_json=context_pack.model_dump(mode="json"),
                source_refs=(context_pack.included_chat_summary_ref or "chat_summary:none",),
            )
        )
        self._context_repository.save_context_pack(context_pack)
        self._context_repository.record_lineage_edge(
            run_id=command.run_id,
            from_ref=context_pack.context_pack_id,
            to_ref=readiness_artifact.artifact_id,
            edge_type="source_ref",
        )
        if context_pack.included_chat_summary_ref:
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=context_pack.context_pack_id,
                to_ref=context_pack.included_chat_summary_ref,
                edge_type="source_ref",
            )
        return context_pack

    def _execute_domain_task(
        self,
        *,
        command: UserQnaCommand,
        context_pack: ContextPack,
        domain_task: Any,
    ) -> WorkerExecutionBundle:
        """Plan and execute WorkerAgent steps for one ExpertAgent task."""
        parent_token = self._main_runtime.issued_tokens.get(domain_task.capability_token_ref)
        if parent_token is None:
            raise AgentRuntimeUnavailableError(
                f"missing capability token for {domain_task.domain_task_id}"
            )
        worker_cards = self._capability_registry.visible_worker_cards(
            domain=domain_task.domain,
            capability_token=parent_token,
            required_output_types=domain_task.required_output_types,
        )
        current_domain_task = domain_task
        latest_bundle: WorkerExecutionBundle | None = None
        for attempt_index in range(2):
            try:
                worker_plan = self._expert_planner.plan(
                    domain_task=current_domain_task,
                    worker_cards=worker_cards,
                    context_pack=context_pack,
                )
            except RuntimeError as exc:
                latest_bundle = _blocked_domain_planning_bundle(
                    domain_task=current_domain_task,
                    error_code="expert_plan_invalid",
                    summary=str(exc),
                )
                current_domain_task = _domain_task_with_reflection_feedback(
                    current_domain_task,
                    attempt_index=attempt_index + 1,
                    bundle=latest_bundle,
                )
                continue
            domain_runtime = DomainRuntime(expert_agent_name=domain_task.to_domain_agent)
            bundles: list[WorkerExecutionBundle] = []
            for step in worker_plan.steps:
                if step.kind is not PlanActionKind.EXECUTE:
                    bundles.append(
                        _non_execute_worker_plan_bundle(
                            domain_task=current_domain_task,
                            step=step,
                        )
                    )
                    continue
                worker_task = self._worker_task_from_step(
                    domain_runtime=domain_runtime,
                    domain_task=current_domain_task,
                    parent_token=parent_token,
                    step=step,
                    command=command,
                )
                worker_token = domain_runtime.issued_tokens.get(
                    worker_task.capability_token_ref
                )
                bundles.append(
                    self._execute_worker_task(
                        worker_task,
                        command,
                        context_pack,
                        worker_token,
                    )
                )
            latest_bundle = _merge_worker_bundles(bundles)
            latest_bundle = _audit_worker_bundle(
                latest_bundle,
                required_output_types=_required_outputs_from_worker_plan(
                    worker_plan.steps,
                    current_domain_task.required_output_types,
                ),
            )
            if latest_bundle.result.status is AgentExecutionStatus.SUCCEEDED:
                return latest_bundle
            current_domain_task = _domain_task_with_reflection_feedback(
                current_domain_task,
                attempt_index=attempt_index + 1,
                bundle=latest_bundle,
            )
        if latest_bundle is None:
            raise AgentRuntimeUnavailableError("ExpertAgent produced no worker execution")
        return latest_bundle

    def _worker_task_from_step(
        self,
        *,
        domain_runtime: DomainRuntime,
        domain_task: Any,
        parent_token: CapabilityToken,
        step: WorkerPlanStepDraft,
        command: UserQnaCommand,
    ) -> WorkerTaskRequest:
        """Create the L2-to-L3 request selected by ExpertAgent planning."""
        if step.worker_agent is None or step.skill_id is None:
            raise AgentRuntimeUnavailableError("execute worker step is missing worker identity")
        required_output_types = step.required_output_types or domain_task.required_output_types
        task_goal = _worker_task_goal(
            user_message=command.message,
            conversation_context=tuple(command.conversation_context),
            expert_task=domain_task.task_goal,
            worker_task=step.task,
            worker_inputs=step.constraints.get("worker_inputs"),
        )
        return domain_runtime.create_worker_tasks(
            domain_request=domain_task,
            parent_token=parent_token,
            worker_agent_name=step.worker_agent,
            skill_id=step.skill_id,
            required_output_types=tuple(required_output_types),
            task_goal=task_goal,
            constraints=step.constraints,
            worker_task_id=f"wt_{domain_task.domain_task_id.removeprefix('dt_')}_{step.step_id}",
        )[0]

    def _execute_worker_task(
        self,
        worker_task: WorkerTaskRequest,
        command: UserQnaCommand,
        context_pack: ContextPack,
        capability_token: CapabilityToken | None,
    ) -> WorkerExecutionBundle:
        """Execute a WorkerAgent selected by the ExpertAgent worker plan."""
        bundle = self._worker_runtime.execute(
            worker_task,
            WorkerExecutionContext(
                command=command,
                context_pack=context_pack,
                context_store=self._context_store,
                context_repository=self._context_repository,
                tool_gateway=self._tool_gateway,
                capability_token=capability_token,
                llm_provider_factory=self._llm_provider_factory,
            ),
        )
        if not isinstance(bundle, WorkerExecutionBundle):
            return WorkerExecutionBundle(
                result=bundle,
                artifacts=(),
                answer=None,
                table_rows=[],
            )
        return bundle


def _default_worker_executor_registry(
    *,
    data_question_worker: DataQuestionWorker | None,
    dashboard_services: DashboardServiceBundle,
    llm_provider_factory: Callable[[], LLMProvider],
) -> ExecutorRegistry:
    """Return default WorkerAgent executors for the v1 user-Q&A service."""
    registry = ExecutorRegistry()
    registry.register_spec(
        ExecutorSpec(
            agent_name="DataQuestionWorker",
            skill_id="answer_financial_metric",
            executor=DataQuestionWorkerExecutor(data_question_worker),
            runtime="langgraph",
            required_tools=_DATA_QUESTION_TOOL_ALLOWLIST,
            output_artifact_types=_DATA_QUESTION_OUTPUT_TYPES,
            domain="data",
        )
    )
    registry.register_spec(
        ExecutorSpec(
            agent_name="GeneralQnaWorker",
            skill_id="answer_general_qna",
            executor=GeneralQnaWorkerExecutor(
                dashboard_services=dashboard_services,
                llm_provider_factory=llm_provider_factory,
            ),
            runtime="deterministic",
            required_tools=("dashboard.read_candidates",),
            output_artifact_types=_GENERAL_QNA_OUTPUT_TYPES,
            domain="general",
        )
    )
    return registry


def _synthesize_domain_answer_fragments(
    fragments: list[DomainAnswerFragment],
) -> str:
    """Synthesize final answer text from approved domain fragments."""
    if not fragments:
        raise AgentRuntimeUnavailableError("No domain answer fragments available")
    if len(fragments) == 1:
        fragment = fragments[0]
        if fragment.status is AgentExecutionStatus.SUCCEEDED:
            return fragment.answer
        return "\n\n".join(
            (
                "### 暂时无法完成",
                f"- {fragment.answer}",
                "### 下一步",
                "- 补充缺失输入、启用对应能力，或稍后重试不可用的数据源。",
            )
        )
    if all(fragment.status is not AgentExecutionStatus.SUCCEEDED for fragment in fragments):
        sections = ["### 暂时无法完成"]
        for fragment in fragments:
            sections.append(f"#### {fragment.domain_agent}\n{fragment.answer}")
        sections.append("### 下一步\n- 补充缺失输入、启用对应能力，或稍后重试不可用的数据源。")
        return "\n\n".join(sections)
    sections = ["### 综合回答"]
    for fragment in fragments:
        sections.append(
            "\n".join(
                (
                    f"#### {fragment.domain_agent} ({fragment.status})",
                    fragment.answer,
                )
            )
        )
    return "\n\n".join(sections)


def _planner_messages_answer(messages: tuple[dict[str, Any], ...]) -> str:
    """Return a concise blocked answer from non-executable MainAgent plan messages."""
    details = []
    for message in messages:
        text = str(
            message.get("user_safe_message")
            or message.get("reason")
            or "当前能力不可执行。"
        ).strip()
        if text:
            details.append(text)
    if not details:
        details.append("MainAgent 没有找到当前环境中可执行的专家能力。")
    lines = ["### 暂时无法完成", *[f"- {detail}" for detail in dict.fromkeys(details)]]
    lines.extend(
        [
            "### 下一步",
            "- 启用对应 worker/tool/repository 后重试，或改问当前已开放的数据/普通问答能力。",
        ]
    )
    return "\n\n".join(lines)


def _merge_worker_bundles(bundles: list[WorkerExecutionBundle]) -> WorkerExecutionBundle:
    """Merge worker outputs for one domain task in plan order."""
    if not bundles:
        raise AgentRuntimeUnavailableError("ExpertAgent produced no executable worker outputs")
    artifacts = tuple(artifact for bundle in bundles for artifact in bundle.artifacts)
    table_rows: list[dict[str, Any]] = []
    for bundle in bundles:
        table_rows.extend(bundle.table_rows)
    answer = next((bundle.answer for bundle in reversed(bundles) if bundle.answer), None)
    last_result = bundles[-1].result
    return WorkerExecutionBundle(
        result=last_result.model_copy(
            update={
                "output_artifact_refs": tuple(artifact.artifact_id for artifact in artifacts)
                or last_result.output_artifact_refs,
            }
        ),
        artifacts=artifacts,
        answer=answer,
        table_rows=table_rows,
    )


def _required_outputs_from_worker_plan(
    steps: tuple[WorkerPlanStepDraft, ...],
    fallback_required_outputs: tuple[str, ...],
) -> tuple[str, ...]:
    """Return required output types declared by ExpertAgent worker planning."""
    required: list[str] = []
    for step in steps:
        required.extend(step.required_output_types)
    if not required:
        required.extend(fallback_required_outputs)
    return tuple(dict.fromkeys(required))


def _non_execute_worker_plan_bundle(
    *,
    domain_task: Any,
    step: WorkerPlanStepDraft,
) -> WorkerExecutionBundle:
    """Convert a blocked/clarification worker plan step into a runtime bundle."""
    summary = step.user_safe_message or step.reason or f"Worker plan returned {step.kind}."
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=domain_task.run_id,
            domain_task_id=domain_task.domain_task_id,
            worker_task_id=f"wt_{domain_task.domain_task_id.removeprefix('dt_')}_{step.step_id}",
            worker_agent=step.worker_agent or domain_task.to_domain_agent,
            skill_id=step.skill_id or str(step.kind),
            status=AgentExecutionStatus.BLOCKED,
            error_code=str(step.kind),
            retryable=step.kind is PlanActionKind.ASK_CLARIFICATION,
            safe_summary=summary,
        ),
        artifacts=(),
        answer=None,
        table_rows=[],
    )


def _blocked_domain_planning_bundle(
    *,
    domain_task: Any,
    error_code: str,
    summary: str,
) -> WorkerExecutionBundle:
    """Return a blocked bundle for an ExpertAgent planning failure."""
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=domain_task.run_id,
            domain_task_id=domain_task.domain_task_id,
            worker_task_id=f"wt_{domain_task.domain_task_id.removeprefix('dt_')}_blocked",
            worker_agent=domain_task.to_domain_agent,
            skill_id="expert_plan",
            status=AgentExecutionStatus.BLOCKED,
            error_code=error_code,
            retryable=True,
            safe_summary=summary,
        ),
        artifacts=(),
        answer=None,
        table_rows=[],
    )


def _audit_worker_bundle(
    bundle: WorkerExecutionBundle,
    *,
    required_output_types: tuple[str, ...],
) -> WorkerExecutionBundle:
    """Block WorkerAgent output when required artifacts are missing."""
    if bundle.result.status is not AgentExecutionStatus.SUCCEEDED:
        return bundle
    produced_types = {artifact.artifact_type for artifact in bundle.artifacts}
    missing = tuple(output for output in required_output_types if output not in produced_types)
    if not missing:
        return bundle
    return WorkerExecutionBundle(
        result=bundle.result.model_copy(
            update={
                "status": AgentExecutionStatus.BLOCKED,
                "error_code": "missing_required_artifacts",
                "retryable": True,
                "safe_summary": "Worker output missing required artifacts: " + ", ".join(missing),
            }
        ),
        artifacts=bundle.artifacts,
        answer=None,
        table_rows=bundle.table_rows,
    )


def _domain_task_with_reflection_feedback(
    domain_task: Any,
    *,
    attempt_index: int,
    bundle: WorkerExecutionBundle,
) -> Any:
    """Return a domain task copy with worker failure feedback for replanning."""
    constraints = dict(domain_task.constraints)
    constraints["reflection_feedback"] = {
        "attempt_index": attempt_index,
        "failed_worker_agent": bundle.result.worker_agent,
        "failed_skill_id": bundle.result.skill_id,
        "status": str(bundle.result.status),
        "error_code": bundle.result.error_code,
        "safe_summary": bundle.result.safe_summary,
    }
    return domain_task.model_copy(update={"constraints": constraints})


def _blocked_worker_bundle(
    worker_task: WorkerTaskRequest,
    *,
    error_code: str,
    summary: str,
) -> WorkerExecutionBundle:
    """Return a blocked worker bundle without artifacts."""
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=worker_task.run_id,
            domain_task_id=worker_task.domain_task_id,
            worker_task_id=worker_task.worker_task_id,
            worker_agent=worker_task.worker_agent,
            skill_id=worker_task.skill_id,
            status=AgentExecutionStatus.BLOCKED,
            error_code=error_code,
            retryable=True,
            safe_summary=summary,
        ),
        artifacts=(),
        answer=None,
        table_rows=[],
    )


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


def _first_artifact_of_type(
    artifacts: tuple[ContextArtifact, ...],
    artifact_type: str,
) -> ContextArtifact | None:
    """Return the first artifact of a requested type."""
    return next(
        (artifact for artifact in artifacts if artifact.artifact_type == artifact_type),
        None,
    )


def _empty_analysis_table_artifact(run_id: str, *, suffix: str = "") -> ContextArtifact:
    """Return a traceable empty table when a worker did not need tabular output."""
    suffix_part = f"_{_artifact_id_part(suffix)}" if suffix else ""
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}{suffix_part}_empty_analysis_table",
        run_id=run_id,
        artifact_type="analysis_table",
        producer_agent="AgentRuntimeService",
        payload_json={"columns": [], "rows": []},
        source_refs=("agent:v1:user_qna",),
    )


def _qna_answer_artifact(
    *,
    run_id: str,
    answer: str,
    language: str,
    producer_agent: str,
) -> ContextArtifact:
    """Return the worker-produced Q&A answer artifact."""
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}_{_artifact_id_part(producer_agent)}_qna_answer",
        run_id=run_id,
        artifact_type="qna_answer",
        producer_agent=producer_agent,
        payload_json={
            "answer": answer,
            "language": language,
            "runtime_version": USER_QNA_RUNTIME_VERSION,
        },
        source_refs=("agent:v1:user_qna",),
    )


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


def _root_capability_token(run_id: str) -> CapabilityToken:
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
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(
            ToolPolicy.READ_ONLY_TOOLS,
            ToolPolicy.RETRIEVAL_TOOLS,
            ToolPolicy.QUANT_TOOLS,
            ToolPolicy.DATA_SYNC_TOOLS,
        ),
        allowed_artifact_types=_DEFAULT_ALLOWED_ARTIFACT_TYPES,
        allowed_tool_names=(
            "dashboard.read_candidates",
            "analysis_mart.read_snapshot",
            "evidence.read_package",
            "provider.read_status",
            *_DATA_QUESTION_TOOL_ALLOWLIST,
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=8,
        max_result_bytes=64_000,
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


def _skill_for_domain_task(domain: str) -> str:
    """Return the primary user-Q&A worker skill for a domain task."""
    if domain == "general":
        return "answer_general_qna"
    if domain == "data":
        return "answer_data_status"
    if domain == "quant":
        return "answer_quant_status"
    if domain == "evidence":
        return "answer_evidence_status"
    return "answer_research_status"


def _references_from_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    """Return safe frontend references for table rows."""
    references = [
        {
            "type": "dashboard_candidate",
            "id": str(row["security_id"]),
            "label": str(row["security_id"]),
        }
        for row in rows[:10]
    ]
    return tuple(references)


def _conversation_hash(command: UserQnaCommand) -> str:
    """Return a stable short hash for the conversation summary reference."""
    raw = "|".join(
        f"{item.get('role', '')}:{item.get('content', '')}"
        for item in command.conversation_context
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
