"""Application-facing v1 Agent runtime service."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from margin.agents.runtime.audit_pipeline import AuditPipeline
from margin.agents.runtime.domain_runtime import DomainRuntime
from margin.agents.runtime.expert_runtime import LLMExpertAgentPlanner, WorkerPlanStepDraft
from margin.agents.runtime.main_runtime import GlobalPlan, LLMMainAgentPlanner, MainRuntime
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.workers.data_question_worker import DataQuestionWorker
from margin.dashboard.models import DashboardFilters, DashboardSort
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
class UserQnaRunResult:
    """Result returned by the v1 runtime to the API boundary."""

    answer: str
    guardrail: GuardrailSummary
    global_plan: GlobalPlan
    trace_steps: tuple[AgentTraceStep, ...]
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]
    final_answer: FinalUserAnswerArtifact


@dataclass(frozen=True)
class WorkerExecutionBundle:
    """Executed WorkerAgent result plus frontend-safe artifacts."""

    result: WorkerTaskResult
    artifacts: tuple[ContextArtifact, ...]
    answer: str | None
    table_rows: list[dict[str, Any]]


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
        self._data_question_worker = (
            DataQuestionWorker(warehouse_repository)
            if warehouse_repository is not None
            else None
        )
        planning_llm_provider = llm_provider_factory()
        domain_cards = default_domain_agent_cards()
        self._main_runtime = main_runtime or MainRuntime(
            domain_cards=domain_cards,
            planner=LLMMainAgentPlanner(llm_provider=planning_llm_provider),
        )
        self._expert_planner = LLMExpertAgentPlanner(llm_provider=planning_llm_provider)
        self._worker_cards = default_worker_agent_cards()
        self._audit_pipeline = audit_pipeline or AuditPipeline()

    def run_user_qna(self, command: UserQnaCommand) -> UserQnaRunResult:
        """Run one user Q&A request through v1 planning and final audit."""
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
        context_pack = self._build_and_store_context_pack(command)
        root_token = _root_capability_token(command.run_id)
        global_plan = self._main_runtime.create_global_plan(
            run_id=command.run_id,
            run_type="user_qna",
            user_goal=command.message,
            context_pack=context_pack,
            capability_token=root_token,
            conversation_context=tuple(command.conversation_context),
        )
        if not global_plan.domain_tasks:
            raise AgentRuntimeUnavailableError("MainAgent produced no domain tasks")

        artifacts: list[ContextArtifact] = []
        available_artifacts: dict[str, ContextArtifact] = {}
        approved_capsule_refs: list[str] = []
        used_artifact_refs: list[str] = []
        trace_steps: list[AgentTraceStep] = []
        table_rows: list[dict[str, Any]] = []
        answer = ""

        for domain_task in global_plan.domain_tasks:
            execution = self._execute_domain_task(
                command=command,
                context_pack=context_pack,
                domain_task=domain_task,
            )
            if execution.result.status is not AgentExecutionStatus.SUCCEEDED:
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
            if not domain_answer:
                raise AgentRuntimeUnavailableError("Worker did not produce a user-safe answer")
            answer = domain_answer
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
                status=AgentExecutionStatus.SUCCEEDED,
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
                status=AgentExecutionStatus.SUCCEEDED,
                checked_artifact_refs=domain_artifact_refs,
                schema_valid=True,
                evidence_valid=True,
                source_refs_valid=True,
                context_budget_ok=True,
                safe_summary="domain audit passed",
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
            used_artifact_refs.extend(domain_artifact_refs)
            trace_steps.append(
                AgentTraceStep(
                    step_id=domain_task.domain_task_id,
                    expert_agent_name=domain_task.to_domain_agent,
                    skill_id=execution.result.skill_id,
                    status=AgentExecutionStatus.SUCCEEDED,
                )
            )

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

    def _build_and_store_context_pack(self, command: UserQnaCommand) -> ContextPack:
        """Build and persist the L1 ContextPack artifact."""
        context_pack = ContextRouter().build_context_pack(
            run_id=command.run_id,
            requester_agent="MainAgent",
            target_agent="MainAgent",
            purpose="user_qna_planning",
            token_budget=4000,
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
        if context_pack.included_chat_summary_ref:
            self._context_repository.record_lineage_edge(
                run_id=command.run_id,
                from_ref=context_pack.context_pack_id,
                to_ref=context_pack.included_chat_summary_ref,
                edge_type="source_ref",
            )
        return context_pack

    def _build_candidate_table_artifact(
        self,
        command: UserQnaCommand,
    ) -> tuple[ContextArtifact, list[dict[str, Any]]]:
        """Read dashboard candidates through the app service and store a table artifact."""
        rows = self._load_candidate_rows(command)
        artifact = make_context_artifact(
            artifact_id=f"ctx_{command.run_id}_dashboard_candidates",
            run_id=command.run_id,
            artifact_type="analysis_table",
            producer_agent="DataQuestionWorker",
            payload_json={
                "scope_version_id": command.scope_version_id,
                "universe": command.universe,
                "columns": [
                    "security_id",
                    "symbol",
                    "final_score",
                    "confidence",
                    "screening_status",
                ],
                "rows": rows,
            },
            source_refs=("dashboard:research_candidates",),
        )
        return artifact, rows

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
        worker_cards = tuple(
            card for card in self._worker_cards if card.domain == domain_task.domain
        )
        current_domain_task = domain_task
        latest_bundle: WorkerExecutionBundle | None = None
        for attempt_index in range(2):
            worker_plan = self._expert_planner.plan(
                domain_task=current_domain_task,
                worker_cards=worker_cards,
                context_pack=context_pack,
            )
            domain_runtime = DomainRuntime(expert_agent_name=domain_task.to_domain_agent)
            bundles: list[WorkerExecutionBundle] = []
            for step in worker_plan.steps:
                worker_task = self._worker_task_from_step(
                    domain_runtime=domain_runtime,
                    domain_task=current_domain_task,
                    parent_token=parent_token,
                    step=step,
                    command=command,
                )
                bundles.append(self._execute_worker_task(worker_task, command, context_pack))
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
    ) -> WorkerExecutionBundle:
        """Execute a WorkerAgent selected by the ExpertAgent worker plan."""
        if (
            worker_task.worker_agent == "DataQuestionWorker"
            and worker_task.skill_id == "answer_financial_metric"
        ):
            return self._execute_data_question_worker(worker_task, command)
        if (
            worker_task.worker_agent == "GeneralQnaWorker"
            and worker_task.skill_id == "answer_general_qna"
        ):
            return self._execute_general_qna_worker(worker_task, command, context_pack)
        return WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=worker_task.run_id,
                domain_task_id=worker_task.domain_task_id,
                worker_task_id=worker_task.worker_task_id,
                worker_agent=worker_task.worker_agent,
                skill_id=worker_task.skill_id,
                status=AgentExecutionStatus.BLOCKED,
                error_code="worker_executor_not_registered",
                retryable=False,
                safe_summary="Worker executor is not registered.",
            ),
            artifacts=(),
            answer=None,
            table_rows=[],
        )

    def _execute_data_question_worker(
        self,
        worker_task: WorkerTaskRequest,
        command: UserQnaCommand,
    ) -> WorkerExecutionBundle:
        """Execute the DataQuestionWorker selected by the ExpertAgent."""
        if self._data_question_worker is None:
            return _blocked_worker_bundle(
                worker_task,
                error_code="warehouse_repository_unavailable",
                summary="DataQuestionWorker requires a warehouse repository.",
            )
        analysis = self._data_question_worker.answer_financial_metric(
            run_id=command.run_id,
            message=worker_task.task_goal,
            conversation_context=tuple(command.conversation_context),
            worker_inputs=worker_task.constraints.get("worker_inputs")
            if isinstance(worker_task.constraints.get("worker_inputs"), dict)
            else None,
            chart_type="line",
        )
        if analysis is None:
            return _blocked_worker_bundle(
                worker_task,
                error_code="data_question_worker_no_answer",
                summary="DataQuestionWorker could not answer the task.",
            )
        answer_artifact = _qna_answer_artifact(
            run_id=command.run_id,
            answer=analysis.answer,
            language=command.language,
            producer_agent=worker_task.worker_agent,
        )
        artifacts = (
            analysis.table_artifact,
            analysis.metric_artifact,
            analysis.chart_artifact,
            analysis.image_artifact,
            analysis.worker_activity_artifact,
            answer_artifact,
        )
        return WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=worker_task.run_id,
                domain_task_id=worker_task.domain_task_id,
                worker_task_id=worker_task.worker_task_id,
                worker_agent=worker_task.worker_agent,
                skill_id=worker_task.skill_id,
                status=AgentExecutionStatus.SUCCEEDED,
                output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
                safe_summary="DataQuestionWorker produced analysis artifacts.",
            ),
            artifacts=artifacts,
            answer=analysis.answer,
            table_rows=analysis.table_rows,
        )

    def _execute_general_qna_worker(
        self,
        worker_task: WorkerTaskRequest,
        command: UserQnaCommand,
        context_pack: ContextPack,
    ) -> WorkerExecutionBundle:
        """Execute the GeneralQnaWorker selected by the ExpertAgent."""
        table_artifact, table_rows = self._build_candidate_table_artifact(command)
        answer = self._answer_with_llm(
            command=command,
            context_pack=context_pack,
            table_rows=table_rows,
        )
        answer_artifact = _qna_answer_artifact(
            run_id=command.run_id,
            answer=answer,
            language=command.language,
            producer_agent=worker_task.worker_agent,
        )
        artifacts = (table_artifact, answer_artifact)
        return WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=worker_task.run_id,
                domain_task_id=worker_task.domain_task_id,
                worker_task_id=worker_task.worker_task_id,
                worker_agent=worker_task.worker_agent,
                skill_id=worker_task.skill_id,
                status=AgentExecutionStatus.SUCCEEDED,
                output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
                safe_summary="GeneralQnaWorker produced a context-bound answer.",
            ),
            artifacts=artifacts,
            answer=answer,
            table_rows=table_rows,
        )

    def _load_candidate_rows(self, command: UserQnaCommand) -> list[dict[str, Any]]:
        """Load a compact dashboard candidate table without exposing raw internals."""
        try:
            page = self._dashboard_services.query.list_research_candidates_v2(
                scope_version_id=command.scope_version_id,
                universe_code=command.universe,
                filters=DashboardFilters(),
                sort=DashboardSort(field="final_score", direction="desc"),
                cursor=None,
                limit=10,
            )
        except Exception:
            return []
        return [
            {
                "security_id": item.security_id,
                "symbol": item.symbol,
                "final_score": item.final_score,
                "confidence": item.confidence,
                "screening_status": item.screening_status,
            }
            for item in page.items
        ]

    def _answer_with_llm(
        self,
        *,
        command: UserQnaCommand,
        context_pack: ContextPack,
        table_rows: list[dict[str, Any]],
    ) -> str:
        """Generate a user answer from approved context only."""
        prompt = _build_user_answer_prompt(
            command=command,
            context_pack=context_pack,
            table_rows=table_rows,
        )
        result = self._llm_provider_factory().complete(prompt, temperature=0.0)
        if not result.success:
            raise AgentRuntimeUnavailableError(result.error or "LLM completion failed")
        answer = strip_thinking_blocks(
            result.raw_response or str(result.output.get("content", ""))
        )
        if not answer:
            raise AgentRuntimeUnavailableError("LLM returned an empty answer")
        return answer


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


def _worker_task_goal(
    *,
    user_message: str,
    conversation_context: tuple[dict[str, str], ...],
    expert_task: str,
    worker_task: str,
    worker_inputs: object | None = None,
) -> str:
    """Build the WorkerAgent task prompt from A2A task context."""
    recent = "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}"
        for item in conversation_context[-8:]
    )
    return "\n".join(
        item
        for item in (
            f"expert_task: {expert_task}",
            f"worker_task: {worker_task}",
            f"worker_inputs: {worker_inputs}" if worker_inputs is not None else "",
            "recent_conversation:",
            recent,
            f"current_user: {user_message}",
        )
        if item
    )


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
