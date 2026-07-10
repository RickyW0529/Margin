"""A2A endpoints for the MainAgent -> ExpertAgent -> WorkerAgent hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
    Task,
    TaskState,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agents.a2a import (
    IN_PROCESS_BINDING,
    LOSSLESS_JSON_EXTENSION_URI,
    A2ATransport,
    AgentCall,
    AgentResult,
    SyncA2AClient,
    make_data_artifact,
    read_data_part,
)
from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.context.repository import ContextRepository
from margin.agents.protocol.execution import (
    AgentRunContext,
    DomainDispatchEnvelope,
    DomainExecutionEnvelope,
    WorkerDispatchEnvelope,
    WorkerExecutionEnvelope,
)
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    DomainAuditReport,
    DomainContextCapsule,
    DomainTaskRequest,
    DomainTaskResult,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.protocol.planning import PlanActionKind
from margin.agents.runtime.capability_registry import CapabilityRegistry
from margin.agents.runtime.dag import (
    DAGExecutionResult,
    DAGNodeStatus,
    DAGStepRunResult,
    PlanDAGExecutor,
)
from margin.agents.runtime.domain_runtime import DomainRuntime
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
)
from margin.agents.runtime.expert_runtime import (
    CapabilityExpertPlanner,
    ExpertWorkerPlanDraft,
    LLMExpertAgentPlanner,
    WorkerPlanStepDraft,
)
from margin.agents.runtime.main_runtime import GlobalPlan
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityAuthority
from margin.agents.tools.gateway import ToolAuditStore, ToolGateway
from margin.core.hashing import stable_json_hash


@dataclass(frozen=True)
class ExpertReviewPolicy:
    """Bounded replanning policy applied after ExpertAgent output review."""

    max_plan_attempts: int = 2

    def __post_init__(self) -> None:
        if self.max_plan_attempts < 1:
            raise ValueError("max_plan_attempts must be at least 1")


@dataclass(frozen=True)
class HierarchyExecutionResult:
    """MainAgent-visible results of executing one GlobalPlan."""

    domain_executions: tuple[DomainExecutionEnvelope, ...]
    dag_result: DAGExecutionResult
    a2a_task_ids: tuple[str, ...]


class WorkerAgentEndpoint:
    """A2A endpoint that is the only layer allowed to invoke WorkerRuntime/tools."""

    def __init__(
        self,
        *,
        worker_runtime: WorkerRuntime,
        capability_authority: CapabilityAuthority,
        context_store: AgentContextStore,
        context_repository: ContextRepository,
        tool_gateway: ToolGateway,
        tool_audit_store: ToolAuditStore | None = None,
        llm_provider_factory: Any,
    ) -> None:
        self._worker_runtime = worker_runtime
        self._capability_authority = capability_authority
        self._context_store = context_store
        self._context_repository = context_repository
        self._tool_gateway = tool_gateway
        self._tool_audit_store = tool_audit_store
        self._llm_provider_factory = llm_provider_factory

    def __call__(self, call: AgentCall) -> AgentResult:
        dispatch = WorkerDispatchEnvelope.model_validate(_single_payload(call))
        request = dispatch.task
        if call.source_agent != request.parent_agent:
            raise ValueError("worker task source does not match parent ExpertAgent")
        if request.worker_agent != call.target_agent:
            raise ValueError("worker task addressed to a different WorkerAgent")
        if call.message.context_id != request.run_id:
            raise ValueError("worker task A2A context does not match run")
        if call.message.task_id != request.worker_task_id:
            raise ValueError("worker A2A task id does not match delegated task")
        _validate_dispatch_context(
            run_context=dispatch.run_context,
            context_pack=dispatch.context_pack,
            run_id=request.run_id,
            context_pack_id=request.input_context_pack_ref,
            requester_agent=request.parent_agent,
            target_agent=request.worker_agent,
        )
        token = self._capability_authority.resolve(
            request.capability_token_ref,
            run_id=request.run_id,
            issued_to=request.worker_agent,
            task_id=request.worker_task_id,
            context_pack_id=request.input_context_pack_ref,
            context_pack_hash=dispatch.context_pack.content_hash,
        )
        if token.issued_by != call.source_agent:
            raise ValueError("worker capability issuer does not match A2A source")
        raw_bundle = self._worker_runtime.execute(
            request,
            WorkerExecutionContext(
                command=dispatch.run_context,
                context_pack=dispatch.context_pack,
                context_store=self._context_store,
                context_repository=self._context_repository,
                tool_gateway=self._tool_gateway,
                capability_token=token,
                llm_provider_factory=self._llm_provider_factory,
            ),
        )
        bundle = (
            raw_bundle
            if isinstance(raw_bundle, WorkerExecutionBundle)
            else WorkerExecutionBundle(
                result=raw_bundle,
                artifacts=(),
                answer=None,
                table_rows=[],
            )
        )
        _validate_worker_execution(
            request,
            bundle,
            token.allowed_artifact_types,
            audit_store=self._tool_audit_store,
        )
        for artifact in bundle.artifacts:
            self._context_store.add_artifact(artifact)
        envelope = WorkerExecutionEnvelope(
            result=bundle.result,
            artifacts=bundle.artifacts,
            answer=bundle.answer,
            table_rows=tuple(bundle.table_rows),
        )
        return AgentResult(
            artifacts=(
                make_data_artifact(
                    name="worker-execution",
                    payload=envelope.model_dump(mode="json"),
                ),
            ),
            state=_a2a_state(bundle.result.status, retryable=bundle.result.retryable),
            metadata={
                "run_id": request.run_id,
                "worker_task_id": request.worker_task_id,
                "worker_agent": request.worker_agent,
                "skill_id": request.skill_id,
            },
        )


class ExpertAgentEndpoint:
    """A2A endpoint that plans WorkerAgent DAGs and reviews their artifacts."""

    def __init__(
        self,
        *,
        agent_name: str,
        worker_cards: tuple[WorkerAgentCard, ...],
        planner: LLMExpertAgentPlanner,
        capability_registry: CapabilityRegistry,
        capability_authority: CapabilityAuthority,
        transport: A2ATransport,
        tool_audit_store: ToolAuditStore | None = None,
        review_policy: ExpertReviewPolicy | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self._agent_name = agent_name
        self._worker_cards = worker_cards
        self._planner = planner
        self._fallback_planner = CapabilityExpertPlanner()
        self._capability_registry = capability_registry
        self._capability_authority = capability_authority
        self._client = SyncA2AClient(transport, source_agent=agent_name)
        self._tool_audit_store = tool_audit_store
        self._review_policy = review_policy or ExpertReviewPolicy()
        self._dag_executor = PlanDAGExecutor(max_concurrency=max_concurrency)

    def __call__(self, call: AgentCall) -> AgentResult:
        dispatch = DomainDispatchEnvelope.model_validate(_single_payload(call))
        request = dispatch.task
        if call.source_agent != request.from_agent:
            raise ValueError("domain task source does not match MainAgent")
        if request.to_domain_agent != self._agent_name:
            raise ValueError("domain task addressed to a different ExpertAgent")
        if call.message.context_id != request.run_id:
            raise ValueError("domain task A2A context does not match run")
        if call.message.task_id != _domain_a2a_task_id(request):
            raise ValueError("expert A2A task id does not match delegated task")
        _validate_dispatch_context(
            run_context=dispatch.run_context,
            context_pack=dispatch.context_pack,
            run_id=request.run_id,
            context_pack_id=request.input_context_pack_ref,
            requester_agent=request.from_agent,
            target_agent=request.to_domain_agent,
        )
        parent_token = self._capability_authority.resolve(
            request.capability_token_ref,
            run_id=request.run_id,
            issued_to=self._agent_name,
            task_id=request.domain_task_id,
            context_pack_id=request.input_context_pack_ref,
            context_pack_hash=dispatch.context_pack.content_hash,
        )
        if parent_token.issued_by != call.source_agent:
            raise ValueError("expert capability issuer does not match A2A source")
        visible_cards = self._capability_registry.visible_worker_cards(
            domain=request.domain,
            capability_token=parent_token,
            required_output_types=(),
        )
        current_request = request
        reviewed: DomainExecutionEnvelope | None = None
        for attempt in range(1, self._review_policy.max_plan_attempts + 1):
            plan = self._plan(current_request, visible_cards, dispatch)
            worker_envelopes = self._execute_plan(
                plan=plan,
                dispatch=dispatch.model_copy(update={"task": current_request}),
                parent_token=parent_token,
                visible_cards=visible_cards,
                attempt=attempt,
            )
            review_request = current_request.model_copy(
                update={
                    "required_output_types": _review_output_types(
                        current_request,
                        plan,
                    )
                }
            )
            reviewed = _review_domain_execution(review_request, worker_envelopes)
            if reviewed.result.status is AgentExecutionStatus.SUCCEEDED:
                break
            if not any(envelope.result.retryable for envelope in worker_envelopes):
                break
            current_request = _domain_request_with_review_feedback(
                current_request,
                attempt=attempt,
                reviewed=reviewed,
            )
        if reviewed is None:
            raise RuntimeError("ExpertAgent produced no reviewed result")
        return AgentResult(
            artifacts=(
                make_data_artifact(
                    name="domain-execution",
                    payload=reviewed.model_dump(mode="json"),
                ),
            ),
            state=_a2a_state(
                reviewed.result.status,
                retryable=bool(reviewed.result.retry_suggestions),
            ),
            metadata={
                "run_id": request.run_id,
                "domain_task_id": request.domain_task_id,
                "domain_agent": self._agent_name,
            },
        )

    def _plan(
        self,
        request: DomainTaskRequest,
        visible_cards: tuple[WorkerAgentCard, ...],
        dispatch: DomainDispatchEnvelope,
    ) -> ExpertWorkerPlanDraft:
        try:
            return self._planner.plan(
                domain_task=request,
                worker_cards=visible_cards,
                context_pack=dispatch.context_pack,
            )
        except (RuntimeError, ValueError):
            return self._fallback_planner.plan(
                domain_task=request,
                worker_cards=visible_cards,
                context_pack=dispatch.context_pack,
            )

    def _execute_plan(
        self,
        *,
        plan: ExpertWorkerPlanDraft,
        dispatch: DomainDispatchEnvelope,
        parent_token: Any,
        visible_cards: tuple[WorkerAgentCard, ...],
        attempt: int,
    ) -> tuple[WorkerExecutionEnvelope, ...]:
        domain_runtime = DomainRuntime(expert_agent_name=self._agent_name)
        output_by_step: dict[str, WorkerExecutionEnvelope] = {}
        output_lock = RLock()

        def run_step(step: WorkerPlanStepDraft) -> DAGStepRunResult:
            if step.kind is not PlanActionKind.EXECUTE:
                envelope = _non_execute_worker_envelope(dispatch.task, step, attempt)
                with output_lock:
                    output_by_step[step.step_id] = envelope
                return DAGStepRunResult(
                    status=DAGNodeStatus.FAILED,
                    output=envelope,
                    error_code=envelope.result.error_code,
                    error_message=envelope.result.safe_summary,
                )
            card, skill = _find_visible_skill(
                visible_cards,
                worker_agent=step.worker_agent or "",
                skill_id=step.skill_id or "",
            )
            with output_lock:
                dependency_outputs = tuple(
                    output_by_step[dependency_id]
                    for dependency_id in step.depends_on
                    if dependency_id in output_by_step
                )
            dependency_refs = tuple(
                artifact.artifact_id
                for output in dependency_outputs
                for artifact in output.artifacts
            )
            current_domain_task = dispatch.task.model_copy(
                update={
                    "input_artifact_refs": tuple(
                        dict.fromkeys((*dispatch.task.input_artifact_refs, *dependency_refs))
                    ),
                    "idempotency_key": f"{dispatch.task.idempotency_key}:attempt:{attempt}",
                }
            )
            worker_task_id = (
                f"wt_{dispatch.task.run_id}_"
                f"{dispatch.task.domain_task_id.removeprefix('dt_')}_"
                f"{step.step_id}_a{attempt}"
            )
            required_outputs = step.required_output_types or skill.output_artifact_types
            worker_task = domain_runtime.create_worker_tasks(
                domain_request=current_domain_task,
                parent_token=parent_token,
                worker_agent_name=card.name,
                skill_id=skill.skill_id,
                required_output_types=required_outputs,
                task_goal=step.task,
                constraints=step.constraints,
                worker_task_id=worker_task_id,
                depends_on=step.depends_on,
                allowed_tool_names=skill.tool_allowlist,
                allowed_artifact_types=skill.output_artifact_types,
                max_tool_calls=card.max_tool_calls,
            )[0]
            worker_token = domain_runtime.issued_tokens[worker_task.capability_token_ref]
            self._capability_authority.issue(worker_token)
            task = self._client.send_data(
                card.name,
                WorkerDispatchEnvelope(
                    run_context=dispatch.run_context,
                    context_pack=_route_context_pack(
                        dispatch.context_pack,
                        requester_agent=self._agent_name,
                        target_agent=card.name,
                        purpose="worker_execution",
                    ),
                    task=worker_task,
                ).model_dump(mode="json"),
                task_id=worker_task.worker_task_id,
                context_id=dispatch.task.run_id,
            )
            envelope = _worker_envelope_from_task(task)
            _validate_worker_execution(
                worker_task,
                WorkerExecutionBundle(
                    result=envelope.result,
                    artifacts=envelope.artifacts,
                    answer=envelope.answer,
                    table_rows=list(envelope.table_rows),
                ),
                worker_token.allowed_artifact_types,
                audit_store=self._tool_audit_store,
            )
            with output_lock:
                output_by_step[step.step_id] = envelope
            succeeded = envelope.result.status in {
                AgentExecutionStatus.SUCCEEDED,
                AgentExecutionStatus.PARTIAL,
            }
            return DAGStepRunResult(
                status=DAGNodeStatus.SUCCEEDED if succeeded else DAGNodeStatus.FAILED,
                output=envelope,
                error_code=envelope.result.error_code,
                error_message=envelope.result.safe_summary,
            )

        dag_result = self._dag_executor.execute(plan.steps, run_step)
        envelopes: list[WorkerExecutionEnvelope] = []
        for result in dag_result.results:
            if isinstance(result.output, WorkerExecutionEnvelope):
                envelopes.append(result.output)
                continue
            if result.status is DAGNodeStatus.SKIPPED:
                envelopes.append(
                    _skipped_worker_envelope(
                        dispatch.task,
                        step_id=result.step_id,
                        failed_dependencies=result.failed_dependency_ids,
                        attempt=attempt,
                    )
                )
            else:
                envelopes.append(
                    _failed_worker_envelope(
                        dispatch.task,
                        step_id=result.step_id,
                        error_code=result.error_code,
                        error_message=result.error_message,
                        attempt=attempt,
                    )
                )
        return tuple(envelopes)


class HierarchicalPlanExecutor:
    """MainAgent-side dispatcher and reviewer input collector."""

    def __init__(
        self,
        *,
        transport: A2ATransport,
        max_concurrency: int = 1,
    ) -> None:
        self._client = SyncA2AClient(transport, source_agent="MainAgent")
        self._dag_executor = PlanDAGExecutor(max_concurrency=max_concurrency)

    def execute(
        self,
        *,
        plan: GlobalPlan,
        run_context: AgentRunContext,
        context_pack: Any,
    ) -> HierarchyExecutionResult:
        outputs: dict[str, DomainExecutionEnvelope] = {}
        output_lock = RLock()
        task_ids: list[str] = []

        def run_domain(task: DomainTaskRequest) -> DAGStepRunResult:
            with output_lock:
                dependency_outputs = tuple(
                    outputs[dependency_id]
                    for dependency_id in task.depends_on
                    if dependency_id in outputs
                )
            dependency_refs = tuple(
                artifact.artifact_id
                for output in dependency_outputs
                for artifact in output.artifacts
            )
            resolved_task = task.model_copy(
                update={
                    "input_artifact_refs": tuple(
                        dict.fromkeys((*task.input_artifact_refs, *dependency_refs))
                    )
                }
            )
            a2a_task_id = _domain_a2a_task_id(task)
            response = self._client.send_data(
                task.to_domain_agent,
                DomainDispatchEnvelope(
                    run_context=run_context,
                    context_pack=_route_context_pack(
                        context_pack,
                        requester_agent="MainAgent",
                        target_agent=task.to_domain_agent,
                        purpose="expert_planning",
                    ),
                    task=resolved_task,
                ).model_dump(mode="json"),
                task_id=a2a_task_id,
                context_id=plan.run_id,
            )
            envelope = _domain_envelope_from_task(response)
            _validate_domain_execution(task, envelope)
            with output_lock:
                outputs[task.domain_task_id] = envelope
                task_ids.append(response.id)
            succeeded = envelope.result.status in {
                AgentExecutionStatus.SUCCEEDED,
                AgentExecutionStatus.PARTIAL,
            }
            return DAGStepRunResult(
                status=DAGNodeStatus.SUCCEEDED if succeeded else DAGNodeStatus.FAILED,
                output=envelope,
                error_message=envelope.result.safe_user_summary,
            )

        dag_result = self._dag_executor.execute(plan.domain_tasks, run_domain)
        tasks_by_id = {task.domain_task_id: task for task in plan.domain_tasks}
        domain_executions = tuple(
            result.output
            if isinstance(result.output, DomainExecutionEnvelope)
            else _review_domain_execution(
                tasks_by_id[result.step_id],
                (
                    (
                        _skipped_worker_envelope(
                            tasks_by_id[result.step_id],
                            step_id="domain_dependency_skip",
                            failed_dependencies=result.failed_dependency_ids,
                            attempt=1,
                        )
                        if result.status is DAGNodeStatus.SKIPPED
                        else _failed_worker_envelope(
                            tasks_by_id[result.step_id],
                            step_id="domain_dispatch",
                            error_code=result.error_code,
                            error_message=result.error_message,
                            attempt=1,
                        )
                    ),
                ),
            )
            for result in dag_result.results
        )
        return HierarchyExecutionResult(
            domain_executions=domain_executions,
            dag_result=dag_result,
            a2a_task_ids=tuple(task_ids),
        )


def register_hierarchy_endpoints(
    *,
    transport: A2ATransport,
    domain_cards: tuple[DomainAgentCard, ...],
    worker_cards: tuple[WorkerAgentCard, ...],
    expert_planner_factory: Any,
    capability_registry: CapabilityRegistry,
    capability_authority: CapabilityAuthority,
    worker_runtime: WorkerRuntime,
    context_store: AgentContextStore,
    context_repository: ContextRepository,
    tool_gateway: ToolGateway,
    tool_audit_store: ToolAuditStore | None = None,
    llm_provider_factory: Any,
    expert_max_concurrency: int = 1,
) -> None:
    """Register every executable ExpertAgent and WorkerAgent as A2A endpoints."""
    worker_endpoint = WorkerAgentEndpoint(
        worker_runtime=worker_runtime,
        capability_authority=capability_authority,
        context_store=context_store,
        context_repository=context_repository,
        tool_gateway=tool_gateway,
        tool_audit_store=tool_audit_store,
        llm_provider_factory=llm_provider_factory,
    )
    for worker_card in worker_cards:
        transport.register(_worker_a2a_card(worker_card), worker_endpoint)
    for domain_card in domain_cards:
        transport.register(
            _domain_a2a_card(domain_card),
            ExpertAgentEndpoint(
                agent_name=domain_card.name,
                worker_cards=worker_cards,
                planner=expert_planner_factory(),
                capability_registry=capability_registry,
                capability_authority=capability_authority,
                transport=transport,
                tool_audit_store=tool_audit_store,
                max_concurrency=expert_max_concurrency,
            ),
        )


def _review_domain_execution(
    request: DomainTaskRequest,
    worker_envelopes: tuple[WorkerExecutionEnvelope, ...],
) -> DomainExecutionEnvelope:
    checked_artifacts = tuple(
        artifact for envelope in worker_envelopes for artifact in envelope.artifacts
    )
    invalid_hash_refs = tuple(
        artifact.artifact_id
        for artifact in checked_artifacts
        if artifact.payload_hash != stable_json_hash(artifact.payload_json)
    )
    artifacts = tuple(
        artifact
        for artifact in checked_artifacts
        if artifact.artifact_id not in invalid_hash_refs
    )
    worker_results = tuple(envelope.result for envelope in worker_envelopes)
    produced_types = {artifact.artifact_type for artifact in artifacts}
    missing = tuple(
        output for output in request.required_output_types if output not in produced_types
    )
    invalid_requirements = tuple(f"invalid_payload_hash:{ref}" for ref in invalid_hash_refs)
    missing_source_refs = tuple(
        artifact.artifact_id for artifact in artifacts if not artifact.source_refs
    )
    source_requirements = tuple(
        f"missing_source_refs:{ref}" for ref in missing_source_refs
    )
    review_failures = (*missing, *invalid_requirements, *source_requirements)
    source_refs_valid = not missing_source_refs
    successful = tuple(
        result
        for result in worker_results
        if result.status is AgentExecutionStatus.SUCCEEDED
    )
    if review_failures or not source_refs_valid:
        status = AgentExecutionStatus.BLOCKED
    elif worker_results and len(successful) == len(worker_results):
        status = AgentExecutionStatus.SUCCEEDED
    elif artifacts or successful:
        status = AgentExecutionStatus.PARTIAL
    else:
        status = AgentExecutionStatus.BLOCKED
    summaries = tuple(
        dict.fromkeys(
            envelope.answer
            for envelope in worker_envelopes
            if envelope.answer
            and envelope.result.status
            in {AgentExecutionStatus.SUCCEEDED, AgentExecutionStatus.PARTIAL}
        )
    )
    answer = "\n\n".join(summaries) or (
        "当前查询暂时无法完成。请确认查询对象、指标和时间范围，或稍后重试。"
    )
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref
            for artifact in artifacts
            for evidence_ref in artifact.evidence_refs
        )
    )
    suffix = request.domain_task_id.removeprefix("dt_")
    capsule = DomainContextCapsule(
        capsule_id=f"dcc_{request.run_id}_{suffix}",
        run_id=request.run_id,
        domain=request.domain,
        purpose="expert_review",
        status=status,
        summary=answer,
        artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
        evidence_refs=evidence_refs,
        open_questions=review_failures,
        source_refs=("a2a:message/send",),
        compression_policy_version="domain-capsule-v2",
        input_hash=request.idempotency_key,
    )
    audit = DomainAuditReport(
        audit_report_id=f"da_{request.run_id}_{suffix}",
        run_id=request.run_id,
        domain_task_id=request.domain_task_id,
        domain=request.domain,
        status=status,
        checked_artifact_refs=tuple(
            artifact.artifact_id for artifact in checked_artifacts
        ),
        schema_valid=not review_failures,
        evidence_valid=not missing,
        source_refs_valid=source_refs_valid,
        context_budget_ok=True,
        missing_requirements=review_failures,
        safe_summary=(
            "ExpertAgent review passed."
            if status is AgentExecutionStatus.SUCCEEDED
            else "ExpertAgent review found missing or blocked worker outputs."
        ),
    )
    capsule_artifact = make_context_artifact(
        artifact_id=capsule.capsule_id,
        run_id=request.run_id,
        artifact_type="domain_context_capsule",
        producer_agent=request.to_domain_agent,
        payload_json=capsule.model_dump(mode="json"),
        source_refs=capsule.source_refs,
        evidence_refs=capsule.evidence_refs,
    )
    audit_artifact = make_context_artifact(
        artifact_id=audit.audit_report_id,
        run_id=request.run_id,
        artifact_type="domain_audit_report",
        producer_agent=request.to_domain_agent,
        payload_json=audit.model_dump(mode="json"),
        source_refs=("a2a:message/send",),
    )
    reviewed_artifacts = (*artifacts, capsule_artifact, audit_artifact)
    result = DomainTaskResult(
        run_id=request.run_id,
        domain_task_id=request.domain_task_id,
        domain_agent=request.to_domain_agent,
        domain=request.domain,
        status=status,
        produced_artifact_refs=tuple(artifact.artifact_id for artifact in reviewed_artifacts),
        domain_context_capsule_ref=capsule.capsule_id,
        domain_audit_report_ref=audit.audit_report_id,
        missing_requirements=review_failures,
        safe_user_summary=answer,
    )
    return DomainExecutionEnvelope(
        result=result,
        capsule=capsule,
        audit=audit,
        artifacts=reviewed_artifacts,
        worker_results=worker_results,
        answer=answer,
        table_rows=tuple(
            row for envelope in worker_envelopes for row in envelope.table_rows
        ),
    )


def _review_output_types(
    request: DomainTaskRequest,
    plan: ExpertWorkerPlanDraft,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *request.required_output_types,
                *(
                    output
                    for step in plan.steps
                    for output in step.required_output_types
                ),
            )
        )
    )


def _find_visible_skill(
    cards: tuple[WorkerAgentCard, ...],
    *,
    worker_agent: str,
    skill_id: str,
) -> tuple[WorkerAgentCard, WorkerSkill]:
    for card in cards:
        if card.name != worker_agent:
            continue
        for skill in card.skills:
            if skill.skill_id == skill_id:
                return card, skill
    raise ValueError(f"worker skill is not visible: {worker_agent}.{skill_id}")


def _worker_envelope_from_task(task: Task) -> WorkerExecutionEnvelope:
    return WorkerExecutionEnvelope.model_validate(_single_task_payload(task))


def _domain_envelope_from_task(task: Task) -> DomainExecutionEnvelope:
    return DomainExecutionEnvelope.model_validate(_single_task_payload(task))


def _domain_a2a_task_id(request: DomainTaskRequest) -> str:
    return f"a2a_{request.run_id}_{request.domain_task_id}"


def _route_context_pack(
    context_pack: ContextPack,
    *,
    requester_agent: str,
    target_agent: str,
    purpose: str,
) -> ContextPack:
    _validate_context_pack_hash(context_pack)
    payload = context_pack.model_dump(mode="json", exclude={"payload_hash"})
    payload.update(
        {
            "requester_agent": requester_agent,
            "target_agent": target_agent,
            "purpose": purpose,
        }
    )
    return ContextPack.model_validate(payload)


def _validate_dispatch_context(
    *,
    run_context: AgentRunContext,
    context_pack: ContextPack,
    run_id: str,
    context_pack_id: str,
    requester_agent: str,
    target_agent: str,
) -> None:
    if run_context.run_id != run_id:
        raise ValueError("dispatch run context does not match delegated task")
    if context_pack.run_id != run_id:
        raise ValueError("dispatch ContextPack run does not match delegated task")
    if context_pack.context_pack_id != context_pack_id:
        raise ValueError("dispatch ContextPack id does not match delegated task")
    if context_pack.requester_agent != requester_agent:
        raise ValueError("dispatch ContextPack requester does not match A2A source")
    if context_pack.target_agent != target_agent:
        raise ValueError("dispatch ContextPack target does not match A2A target")
    _validate_context_pack_hash(context_pack)


def _validate_context_pack_hash(context_pack: ContextPack) -> None:
    payload = context_pack.model_dump(mode="json", exclude={"payload_hash"})
    if context_pack.payload_hash != stable_json_hash(payload):
        raise ValueError("dispatch ContextPack payload hash mismatch")


def _validate_worker_execution(
    request: WorkerTaskRequest,
    bundle: WorkerExecutionBundle,
    allowed_artifact_types: tuple[str, ...],
    *,
    audit_store: ToolAuditStore | None = None,
) -> None:
    result = bundle.result
    identity = (
        result.run_id,
        result.domain_task_id,
        result.worker_task_id,
        result.worker_agent,
        result.skill_id,
    )
    expected = (
        request.run_id,
        request.domain_task_id,
        request.worker_task_id,
        request.worker_agent,
        request.skill_id,
    )
    if identity != expected:
        raise ValueError("Worker result identity does not match delegated task")
    artifact_ids = tuple(artifact.artifact_id for artifact in bundle.artifacts)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("Worker returned duplicate artifact ids")
    if set(result.output_artifact_refs) != set(artifact_ids):
        raise ValueError("Worker result artifact refs do not match returned artifacts")
    allowed_types = set(allowed_artifact_types)
    for artifact in bundle.artifacts:
        if artifact.run_id != request.run_id:
            raise ValueError("Worker artifact belongs to another run")
        if artifact.producer_agent != request.worker_agent:
            raise ValueError("Worker artifact producer does not match delegated WorkerAgent")
        if artifact.artifact_type not in allowed_types:
            raise ValueError("Worker artifact type is outside its capability")
        if artifact.payload_hash != stable_json_hash(artifact.payload_json):
            raise ValueError("Worker artifact payload hash mismatch")
        if not artifact.source_refs:
            raise ValueError("Worker artifact has no source references")
    declared_audits = set(result.audit_event_refs)
    artifact_audits = {
        source_ref
        for artifact in bundle.artifacts
        for source_ref in artifact.source_refs
        if source_ref.startswith("tool_audit_")
    }
    if not artifact_audits.issubset(declared_audits):
        raise ValueError("Worker artifact references undeclared tool audit evidence")
    if audit_store is not None:
        for audit_ref in declared_audits:
            record = audit_store.get_record(audit_ref)
            if record is None:
                raise ValueError("Worker result references unknown tool audit evidence")
            if (
                record.run_id != request.run_id
                or record.task_id != request.worker_task_id
                or record.caller_agent != request.worker_agent
            ):
                raise ValueError("Worker tool audit identity does not match delegated task")


def _validate_domain_execution(
    request: DomainTaskRequest,
    envelope: DomainExecutionEnvelope,
) -> None:
    result = envelope.result
    if (
        result.run_id,
        result.domain_task_id,
        result.domain_agent,
        result.domain,
    ) != (
        request.run_id,
        request.domain_task_id,
        request.to_domain_agent,
        request.domain,
    ):
        raise ValueError("Expert result identity does not match delegated task")
    if envelope.capsule.run_id != request.run_id or envelope.capsule.domain != request.domain:
        raise ValueError("Expert capsule identity does not match delegated task")
    capsule_payload = envelope.capsule.model_dump(mode="json", exclude={"payload_hash"})
    if envelope.capsule.payload_hash != stable_json_hash(capsule_payload):
        raise ValueError("Expert capsule payload hash mismatch")
    if (
        envelope.audit.run_id != request.run_id
        or envelope.audit.domain_task_id != request.domain_task_id
        or envelope.audit.domain != request.domain
    ):
        raise ValueError("Expert audit identity does not match delegated task")
    artifact_by_id = {artifact.artifact_id: artifact for artifact in envelope.artifacts}
    if len(artifact_by_id) != len(envelope.artifacts):
        raise ValueError("Expert returned duplicate artifact ids")
    if set(result.produced_artifact_refs) != set(artifact_by_id):
        raise ValueError("Expert result artifact refs do not match returned artifacts")
    if result.domain_context_capsule_ref != envelope.capsule.capsule_id:
        raise ValueError("Expert result capsule ref mismatch")
    if result.domain_audit_report_ref != envelope.audit.audit_report_id:
        raise ValueError("Expert result audit ref mismatch")
    for artifact in envelope.artifacts:
        if artifact.run_id != request.run_id:
            raise ValueError("Expert artifact belongs to another run")
        if artifact.payload_hash != stable_json_hash(artifact.payload_json):
            raise ValueError("Expert artifact payload hash mismatch")
        if not artifact.source_refs:
            raise ValueError("Expert artifact has no source references")
    capsule_artifact = artifact_by_id.get(envelope.capsule.capsule_id)
    audit_artifact = artifact_by_id.get(envelope.audit.audit_report_id)
    if (
        capsule_artifact is None
        or capsule_artifact.artifact_type != "domain_context_capsule"
        or capsule_artifact.producer_agent != request.to_domain_agent
        or capsule_artifact.payload_json != envelope.capsule.model_dump(mode="json")
    ):
        raise ValueError("Expert capsule artifact does not match the reviewed capsule")
    if (
        audit_artifact is None
        or audit_artifact.artifact_type != "domain_audit_report"
        or audit_artifact.producer_agent != request.to_domain_agent
        or audit_artifact.payload_json != envelope.audit.model_dump(mode="json")
    ):
        raise ValueError("Expert audit artifact does not match the review report")
    worker_artifact_ids = set(artifact_by_id) - {
        envelope.capsule.capsule_id,
        envelope.audit.audit_report_id,
    }
    declared_worker_refs: set[str] = set()
    for worker_result in envelope.worker_results:
        if (
            worker_result.run_id != request.run_id
            or worker_result.domain_task_id != request.domain_task_id
        ):
            raise ValueError("Nested Worker result belongs to another delegated task")
        declared_worker_refs.update(worker_result.output_artifact_refs)
        for artifact_ref in worker_result.output_artifact_refs:
            nested_artifact = artifact_by_id.get(artifact_ref)
            if (
                nested_artifact is None
                or nested_artifact.producer_agent != worker_result.worker_agent
            ):
                raise ValueError("Nested Worker artifact ref or producer mismatch")
    if declared_worker_refs != worker_artifact_ids:
        raise ValueError("Nested Worker results do not account for Expert artifacts")


def _single_payload(call: AgentCall) -> Any:
    if len(call.payloads) != 1:
        raise ValueError("A2A message must contain exactly one structured payload")
    return call.payloads[0]


def _single_task_payload(task: Task) -> Any:
    payloads = [read_data_part(part) for artifact in task.artifacts for part in artifact.parts]
    if len(payloads) != 1:
        raise ValueError("A2A task must contain exactly one structured result artifact")
    return payloads[0]


def _a2a_state(status: AgentExecutionStatus, *, retryable: bool) -> int:
    if status in {AgentExecutionStatus.SUCCEEDED, AgentExecutionStatus.PARTIAL}:
        return TaskState.TASK_STATE_COMPLETED
    if status is AgentExecutionStatus.BLOCKED:
        return (
            TaskState.TASK_STATE_INPUT_REQUIRED
            if retryable
            else TaskState.TASK_STATE_REJECTED
        )
    return TaskState.TASK_STATE_FAILED


def _non_execute_worker_envelope(
    domain_task: DomainTaskRequest,
    step: WorkerPlanStepDraft,
    attempt: int,
) -> WorkerExecutionEnvelope:
    summary = step.user_safe_message or "当前步骤需要补充信息后才能继续。"
    return WorkerExecutionEnvelope(
        result=WorkerTaskResult(
            run_id=domain_task.run_id,
            domain_task_id=domain_task.domain_task_id,
            worker_task_id=(
                f"wt_{domain_task.run_id}_{domain_task.domain_task_id}_"
                f"{step.step_id}_a{attempt}"
            ),
            worker_agent=step.worker_agent or domain_task.to_domain_agent,
            skill_id=step.skill_id or str(step.kind),
            status=AgentExecutionStatus.BLOCKED,
            error_code=str(step.kind),
            retryable=step.kind is PlanActionKind.ASK_CLARIFICATION,
            safe_summary=summary,
        ),
        answer=step.user_safe_message or None,
    )


def _skipped_worker_envelope(
    domain_task: DomainTaskRequest,
    *,
    step_id: str,
    failed_dependencies: tuple[str, ...],
    attempt: int,
) -> WorkerExecutionEnvelope:
    summary = "Worker step skipped because dependencies failed: " + ", ".join(
        failed_dependencies
    )
    return WorkerExecutionEnvelope(
        result=WorkerTaskResult(
            run_id=domain_task.run_id,
            domain_task_id=domain_task.domain_task_id,
            worker_task_id=(
                f"wt_{domain_task.run_id}_{domain_task.domain_task_id}_{step_id}_a{attempt}"
            ),
            worker_agent=domain_task.to_domain_agent,
            skill_id="dependency_skip",
            status=AgentExecutionStatus.BLOCKED,
            error_code="upstream_failed",
            safe_summary=summary,
        ),
        answer=None,
    )


def _failed_worker_envelope(
    domain_task: DomainTaskRequest,
    *,
    step_id: str,
    error_code: str | None,
    error_message: str | None,
    attempt: int,
) -> WorkerExecutionEnvelope:
    summary = error_message or "Worker step failed before producing a result."
    return WorkerExecutionEnvelope(
        result=WorkerTaskResult(
            run_id=domain_task.run_id,
            domain_task_id=domain_task.domain_task_id,
            worker_task_id=(
                f"wt_{domain_task.run_id}_{domain_task.domain_task_id}_{step_id}_a{attempt}"
            ),
            worker_agent=domain_task.to_domain_agent,
            skill_id="dispatch_failure",
            status=AgentExecutionStatus.FAILED,
            error_code=error_code or "agent_dispatch_failed",
            retryable=False,
            safe_summary=summary,
        ),
        answer=None,
    )


def _domain_request_with_review_feedback(
    request: DomainTaskRequest,
    *,
    attempt: int,
    reviewed: DomainExecutionEnvelope,
) -> DomainTaskRequest:
    constraints = dict(request.constraints)
    constraints["expert_review_feedback"] = {
        "attempt": attempt,
        "status": reviewed.result.status,
        "error_code": (
            "missing_required_artifacts"
            if reviewed.result.missing_requirements
            else "worker_execution_incomplete"
        ),
        "missing_requirements": list(reviewed.result.missing_requirements),
        "worker_results": [
            {
                "worker_agent": result.worker_agent,
                "skill_id": result.skill_id,
                "status": result.status,
                "error_code": result.error_code,
            }
            for result in reviewed.worker_results
        ],
    }
    return request.model_copy(update={"constraints": constraints})


def _domain_a2a_card(card: DomainAgentCard) -> AgentCard:
    return _a2a_card(
        name=card.name,
        version=card.version,
        description=card.description,
        skills=(
            AgentSkill(
                id="plan-and-review",
                name="Plan and review",
                description="Plan WorkerAgent tasks and review their artifacts.",
                tags=[card.domain, "expert", "review"],
            ),
        ),
    )


def _worker_a2a_card(card: WorkerAgentCard) -> AgentCard:
    return _a2a_card(
        name=card.name,
        version=card.version,
        description=card.description,
        skills=tuple(
            AgentSkill(
                id=skill.skill_id,
                name=skill.skill_id,
                description=skill.description,
                tags=[card.domain, "worker", *card.supported_runtimes],
            )
            for skill in card.skills
            if not skill.planned_only
        ),
    )


def _a2a_card(
    *,
    name: str,
    version: str,
    description: str,
    skills: tuple[AgentSkill, ...],
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        supported_interfaces=[
            AgentInterface(
                url=f"inprocess://{name}",
                protocol_binding=IN_PROCESS_BINDING,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version=version,
        capabilities=AgentCapabilities(
            extensions=[
                AgentExtension(
                    uri=LOSSLESS_JSON_EXTENSION_URI,
                    description=(
                        "Lossless JSON application envelope used inside A2A DataPart data."
                    ),
                    required=True,
                )
            ]
        ),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=list(skills),
    )
