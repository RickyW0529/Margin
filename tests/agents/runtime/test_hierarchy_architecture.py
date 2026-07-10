"""Architecture tests for the dynamic Main -> Expert -> Worker hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import signature
from typing import Any

import pytest
from a2a.helpers import new_data_message
from a2a.types import Role, SendMessageRequest, SendMessageResponse, Task, TaskState

from margin.agent_runtime.context_store import MemoryAgentContextStore, make_context_artifact
from margin.agents.a2a import (
    LOSSLESS_JSON_EXTENSION_URI,
    AgentCall,
    InProcessA2ATransport,
)
from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.protocol.execution import (
    AgentRunContext,
    WorkerDispatchEnvelope,
    WorkerExecutionEnvelope,
)
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    DomainTaskRequest,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.dag import DAGExecutionStatus
from margin.agents.runtime.execution_context import WorkerExecutionBundle
from margin.agents.runtime.expert_runtime import (
    ExpertWorkerPlanDraft,
    WorkerPlanStepDraft,
)
from margin.agents.runtime.hierarchy import (
    ExpertAgentEndpoint,
    HierarchicalPlanExecutor,
    WorkerAgentEndpoint,
    _review_domain_execution,
    _validate_domain_execution,
    register_hierarchy_endpoints,
)
from margin.agents.runtime.main_runtime import GlobalPlan
from margin.agents.security.capability import CapabilityAuthority, CapabilityToken
from margin.core.hashing import stable_json_hash


class _RecordingTransport(InProcessA2ATransport):
    def __init__(self) -> None:
        super().__init__()
        self.active_targets: list[str] = []
        self.started: list[tuple[str, str, str]] = []
        self.responses: list[SendMessageResponse] = []

    def send_message(
        self,
        target_agent: str,
        request: SendMessageRequest,
        *,
        source_agent: str,
        protocol_version: str,
    ) -> SendMessageResponse:
        self.started.append((source_agent, target_agent, request.message.task_id))
        self.active_targets.append(target_agent)
        try:
            response = super().send_message(
                target_agent,
                request,
                source_agent=source_agent,
                protocol_version=protocol_version,
            )
            self.responses.append(response)
            return response
        finally:
            assert self.active_targets.pop() == target_agent


class _PlannerSpy:
    def __init__(self) -> None:
        self.domain_tasks: list[DomainTaskRequest] = []

    def plan(
        self,
        *,
        domain_task: DomainTaskRequest,
        worker_cards: tuple[WorkerAgentCard, ...],
        context_pack: ContextPack,
    ) -> ExpertWorkerPlanDraft:
        self.domain_tasks.append(domain_task)
        assert [card.name for card in worker_cards] == ["ResearchWorker"]
        assert context_pack.context_pack_id == domain_task.input_context_pack_ref
        assert context_pack.run_id == domain_task.run_id
        return ExpertWorkerPlanDraft(
            steps=(
                WorkerPlanStepDraft(
                    step_id="collect",
                    worker_agent="ResearchWorker",
                    skill_id="execute",
                    task=f"collect evidence for {domain_task.domain_task_id}",
                    required_output_types=("evidence",),
                ),
                WorkerPlanStepDraft(
                    step_id="synthesize",
                    worker_agent="ResearchWorker",
                    skill_id="execute",
                    task=f"synthesize evidence for {domain_task.domain_task_id}",
                    required_output_types=("analysis",),
                    depends_on=("collect",),
                ),
            )
        )


class _CapabilityRegistryStub:
    def __init__(self, worker_card: WorkerAgentCard) -> None:
        self._worker_card = worker_card
        self.required_output_queries: list[tuple[str, ...]] = []

    def visible_worker_cards(self, **kwargs: Any) -> tuple[WorkerAgentCard, ...]:
        self.required_output_queries.append(kwargs["required_output_types"])
        return (self._worker_card,)


class _GatewaySpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def unexpected_call(*args: Any, **kwargs: Any) -> None:
            self.calls.append(name)
            raise AssertionError(f"orchestration called ToolGateway.{name} directly")

        return unexpected_call


class _WorkerRuntimeSpy:
    def __init__(self, transport: _RecordingTransport, gateway: _GatewaySpy) -> None:
        self._transport = transport
        self._gateway = gateway
        self.requests = []
        self.artifacts = {}
        self.active_target_stacks: list[tuple[str, ...]] = []

    def execute(self, request: Any, context: Any) -> WorkerExecutionBundle:
        self.requests.append(request)
        self.active_target_stacks.append(tuple(self._transport.active_targets))
        assert self._transport.active_targets[-1] == "ResearchWorker"
        assert context.tool_gateway is self._gateway
        output_type = request.required_output_types[0]
        artifact_id = f"artifact-{request.worker_task_id}"
        artifact = make_context_artifact(
            artifact_id=artifact_id,
            run_id=request.run_id,
            artifact_type=output_type,
            producer_agent=request.worker_agent,
            payload_json={
                "worker_task_id": request.worker_task_id,
                "input_artifact_refs": list(request.input_artifact_refs),
                "numeric_payload": {
                    "count": 7,
                    "ratio": 1.25,
                    "nested": [1, 2.5, {"rank": 3}],
                },
            },
            source_refs=("worker-runtime-spy",),
            evidence_refs=("evidence:numeric-payload",),
        )
        self.artifacts[artifact_id] = artifact
        return WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=request.run_id,
                domain_task_id=request.domain_task_id,
                worker_task_id=request.worker_task_id,
                worker_agent=request.worker_agent,
                skill_id=request.skill_id,
                status=AgentExecutionStatus.SUCCEEDED,
                output_artifact_refs=(artifact_id,),
                safe_summary=f"completed {request.worker_task_id}",
            ),
            artifacts=(artifact,),
            answer=f"completed {request.worker_task_id}",
            table_rows=[],
        )


def test_hierarchy_uses_a2a_tasks_and_propagates_dag_artifacts() -> None:
    transport = _RecordingTransport()
    gateway = _GatewaySpy()
    worker_runtime = _WorkerRuntimeSpy(transport, gateway)
    planner = _PlannerSpy()
    worker_card = _worker_card()
    capability_registry = _CapabilityRegistryStub(worker_card)
    authority = CapabilityAuthority()
    domain_tasks = (
        _domain_task("dt_first", token_ref="token-first", input_refs=("seed-first",)),
        _domain_task(
            "dt_second",
            token_ref="token-second",
            input_refs=("seed-second",),
            depends_on=("dt_first",),
        ),
    )
    for task in domain_tasks:
        authority.issue(_expert_token(task))

    register_hierarchy_endpoints(
        transport=transport,
        domain_cards=(_domain_card(),),
        worker_cards=(worker_card,),
        expert_planner_factory=lambda: planner,
        capability_registry=capability_registry,  # type: ignore[arg-type]
        capability_authority=authority,
        worker_runtime=worker_runtime,  # type: ignore[arg-type]
        context_store=MemoryAgentContextStore(),
        context_repository=object(),  # type: ignore[arg-type]
        tool_gateway=gateway,  # type: ignore[arg-type]
        llm_provider_factory=lambda: object(),
    )
    assert all(
        any(
            extension.uri == LOSSLESS_JSON_EXTENSION_URI and extension.required
            for extension in card.capabilities.extensions
        )
        for card in transport.list_agents()
    )
    plan = GlobalPlan(
        run_id="run-hierarchy",
        run_type="user_qna",
        user_intent="research two dependent questions",
        domain_tasks=domain_tasks,
    )

    result = HierarchicalPlanExecutor(transport=transport).execute(
        plan=plan,
        run_context=AgentRunContext(
            run_id=plan.run_id,
            trigger="user_qna",
            goal=plan.user_intent,
        ),
        context_pack=_context_pack(),
    )

    assert result.dag_result.status is DAGExecutionStatus.SUCCEEDED
    assert [task.domain_task_id for task in planner.domain_tasks] == [
        "dt_first",
        "dt_second",
    ]
    assert capability_registry.required_output_queries == [(), ()]
    assert result.a2a_task_ids == (
        "a2a_run-hierarchy_dt_first",
        "a2a_run-hierarchy_dt_second",
    )

    expected_task_ids = {
        "a2a_run-hierarchy_dt_first",
        "wt_run-hierarchy_first_collect_a1",
        "wt_run-hierarchy_first_synthesize_a1",
        "a2a_run-hierarchy_dt_second",
        "wt_run-hierarchy_second_collect_a1",
        "wt_run-hierarchy_second_synthesize_a1",
    }
    assert {response.task.id for response in transport.responses} == expected_task_ids
    for task_id in expected_task_ids:
        task = transport.get_task(task_id)
        assert isinstance(task, Task)
        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        assert [status.state for status in transport.get_task_status_history(task_id)] == [
            TaskState.TASK_STATE_SUBMITTED,
            TaskState.TASK_STATE_WORKING,
            TaskState.TASK_STATE_COMPLETED,
        ]

    main_to_expert = [call for call in transport.started if call[1] == "ResearchExpert"]
    expert_to_worker = [call for call in transport.started if call[1] == "ResearchWorker"]
    assert main_to_expert == [
        ("MainAgent", "ResearchExpert", "a2a_run-hierarchy_dt_first"),
        ("MainAgent", "ResearchExpert", "a2a_run-hierarchy_dt_second"),
    ]
    assert len(expert_to_worker) == 4
    assert {source for source, _, _ in expert_to_worker} == {"ResearchExpert"}

    requests = {request.worker_task_id: request for request in worker_runtime.requests}
    first_collect_id = "wt_run-hierarchy_first_collect_a1"
    first_synthesize_id = "wt_run-hierarchy_first_synthesize_a1"
    second_collect_id = "wt_run-hierarchy_second_collect_a1"
    second_synthesize_id = "wt_run-hierarchy_second_synthesize_a1"
    first_collect_artifact = f"artifact-{first_collect_id}"
    assert requests[first_collect_id].input_artifact_refs == ("seed-first",)
    assert first_collect_artifact in requests[first_synthesize_id].input_artifact_refs
    assert requests[first_synthesize_id].depends_on == ("collect",)

    first_domain_artifacts = set(result.domain_executions[0].result.produced_artifact_refs)
    assert first_domain_artifacts
    assert first_domain_artifacts.issubset(
        set(planner.domain_tasks[1].input_artifact_refs)
    )
    assert first_domain_artifacts.issubset(
        set(requests[second_collect_id].input_artifact_refs)
    )
    assert f"artifact-{second_collect_id}" in (
        requests[second_synthesize_id].input_artifact_refs
    )

    received_artifact = next(
        artifact
        for artifact in result.domain_executions[0].artifacts
        if artifact.artifact_id == first_collect_artifact
    )
    original_artifact = worker_runtime.artifacts[first_collect_artifact]
    numeric_payload = received_artifact.payload_json["numeric_payload"]
    assert type(numeric_payload["count"]) is int
    assert type(numeric_payload["ratio"]) is float
    assert type(numeric_payload["nested"][0]) is int
    assert type(numeric_payload["nested"][1]) is float
    assert type(numeric_payload["nested"][2]["rank"]) is int
    assert received_artifact.payload_hash == stable_json_hash(
        received_artifact.payload_json
    )
    assert received_artifact.created_at == original_artifact.created_at
    assert received_artifact.source_refs == original_artifact.source_refs
    assert received_artifact.evidence_refs == original_artifact.evidence_refs

    persistence_store = MemoryAgentContextStore()
    for execution in result.domain_executions:
        for artifact in execution.artifacts:
            persistence_store.add_artifact(artifact)
    assert persistence_store.get_artifact(first_collect_artifact) == received_artifact

    assert worker_runtime.active_target_stacks == [
        ("ResearchExpert", "ResearchWorker"),
    ] * 4
    assert gateway.calls == []

    repeated_step = _domain_task(
        "dt_first",
        token_ref="token-repeated-step",
        input_refs=("seed-repeated",),
        run_id="run-repeated",
        context_pack_id="pack-repeated",
    )
    authority.issue(_expert_token(repeated_step))
    repeated_plan = GlobalPlan(
        run_id="run-repeated",
        run_type="scheduled",
        user_intent="reuse the same planned step in another run",
        domain_tasks=(repeated_step,),
    )

    repeated_result = HierarchicalPlanExecutor(transport=transport).execute(
        plan=repeated_plan,
        run_context=AgentRunContext(
            run_id=repeated_plan.run_id,
            trigger="scheduled",
            goal=repeated_plan.user_intent,
        ),
        context_pack=_context_pack(
            run_id="run-repeated",
            context_pack_id="pack-repeated",
        ),
    )

    assert repeated_result.dag_result.status is DAGExecutionStatus.SUCCEEDED
    assert repeated_result.a2a_task_ids == ("a2a_run-repeated_dt_first",)
    assert transport.get_task("wt_run-repeated_first_collect_a1").status.state == (
        TaskState.TASK_STATE_COMPLETED
    )
    assert capability_registry.required_output_queries == [(), (), ()]
    assert gateway.calls == []


def test_main_and_expert_orchestrators_do_not_accept_execution_dependencies() -> None:
    main_parameters = signature(HierarchicalPlanExecutor).parameters
    expert_parameters = signature(ExpertAgentEndpoint).parameters

    for dependency in ("tool_gateway", "worker_runtime"):
        assert dependency not in main_parameters
        assert dependency not in expert_parameters


def test_worker_endpoint_rejects_a_task_addressed_to_another_worker() -> None:
    endpoint = WorkerAgentEndpoint(
        worker_runtime=object(),  # type: ignore[arg-type]
        capability_authority=object(),  # type: ignore[arg-type]
        context_store=object(),  # type: ignore[arg-type]
        context_repository=object(),  # type: ignore[arg-type]
        tool_gateway=object(),  # type: ignore[arg-type]
        llm_provider_factory=lambda: object(),
    )
    worker_task = WorkerTaskRequest(
        run_id="run-misroute",
        domain_task_id="dt_misroute",
        worker_task_id="wt_misroute",
        parent_agent="ResearchExpert",
        worker_agent="DifferentWorker",
        skill_id="execute",
        task_goal="must not execute",
        input_context_pack_ref="pack-misroute",
        required_output_types=("analysis",),
        tool_policy_ref="token-misroute",
        capability_token_ref="token-misroute",
        token_budget=100,
        max_tool_calls=0,
        deadline_ms=1_000,
        idempotency_key="misroute",
    )
    dispatch = WorkerDispatchEnvelope(
        run_context=AgentRunContext(
            run_id="run-misroute",
            trigger="user_qna",
            goal="must not execute",
        ),
        context_pack=_context_pack(
            run_id="run-misroute",
            context_pack_id="pack-misroute",
        ),
        task=worker_task,
    )
    message = new_data_message(
        dispatch.model_dump(mode="json"),
        role=Role.ROLE_USER,
    )

    with pytest.raises(ValueError, match="different WorkerAgent"):
        endpoint(
            AgentCall(
                source_agent="ResearchExpert",
                target_agent="ResearchWorker",
                protocol_version="1.0",
                request=SendMessageRequest(message=message),
            )
        )


def test_main_review_rejects_capsule_artifact_payload_mismatch() -> None:
    request = _domain_task(
        "dt_integrity",
        token_ref="token-integrity",
        input_refs=(),
    )
    worker_artifact = make_context_artifact(
        artifact_id="artifact-integrity",
        run_id=request.run_id,
        artifact_type="analysis",
        producer_agent="ResearchWorker",
        payload_json={"value": 7},
        source_refs=("worker-runtime",),
    )
    worker_result = WorkerTaskResult(
        run_id=request.run_id,
        domain_task_id=request.domain_task_id,
        worker_task_id="wt_integrity",
        worker_agent="ResearchWorker",
        skill_id="execute",
        status=AgentExecutionStatus.SUCCEEDED,
        output_artifact_refs=(worker_artifact.artifact_id,),
        safe_summary="done",
    )
    reviewed = _review_domain_execution(
        request,
        (
            WorkerExecutionEnvelope(
                result=worker_result,
                artifacts=(worker_artifact,),
                answer="done",
            ),
        ),
    )
    tampered_capsule_artifact = make_context_artifact(
        artifact_id=reviewed.capsule.capsule_id,
        run_id=request.run_id,
        artifact_type="domain_context_capsule",
        producer_agent=request.to_domain_agent,
        payload_json={
            **reviewed.capsule.model_dump(mode="json"),
            "summary": "tampered",
        },
        source_refs=reviewed.capsule.source_refs,
    )
    tampered = reviewed.model_copy(
        update={
            "artifacts": tuple(
                tampered_capsule_artifact
                if artifact.artifact_id == reviewed.capsule.capsule_id
                else artifact
                for artifact in reviewed.artifacts
            )
        }
    )

    with pytest.raises(ValueError, match="does not match the reviewed capsule"):
        _validate_domain_execution(request, tampered)


def _domain_card() -> DomainAgentCard:
    return DomainAgentCard(
        name="ResearchExpert",
        version="1.0",
        domain="research",
        description="Plans and reviews research worker steps.",
        worker_agent_names=("ResearchWorker",),
        required_output_types=("analysis",),
    )


def _worker_card() -> WorkerAgentCard:
    return WorkerAgentCard(
        name="ResearchWorker",
        version="1.0",
        domain="research",
        description="Executes delegated research steps.",
        skills=(
            WorkerSkill(
                skill_id="execute",
                description="Execute a research step.",
                output_artifact_types=("evidence", "analysis"),
            ),
        ),
        max_tool_calls=0,
    )


def _domain_task(
    task_id: str,
    *,
    token_ref: str,
    input_refs: tuple[str, ...],
    depends_on: tuple[str, ...] = (),
    run_id: str = "run-hierarchy",
    context_pack_id: str = "pack-hierarchy",
) -> DomainTaskRequest:
    return DomainTaskRequest(
        run_id=run_id,
        domain_task_id=task_id,
        to_domain_agent="ResearchExpert",
        domain="research",
        user_intent_summary="research request",
        task_goal=f"complete {task_id}",
        required_output_types=("analysis",),
        input_context_pack_ref=context_pack_id,
        input_artifact_refs=input_refs,
        capability_token_ref=token_ref,
        depends_on=depends_on,
        token_budget=2_000,
        deadline_ms=30_000,
        idempotency_key=f"idem-{task_id}",
    )


def _expert_token(task: DomainTaskRequest) -> CapabilityToken:
    return CapabilityToken(
        token_id=task.capability_token_ref,
        run_id=task.run_id,
        issued_by="MainAgent",
        issued_to="ResearchExpert",
        domain="research",
        allowed_artifact_types=("evidence", "analysis"),
        allowed_tool_names=(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        max_tool_calls=0,
        max_result_bytes=1_000_000,
        can_delegate=True,
        delegation_depth_remaining=1,
        bound_task_id=task.domain_task_id,
        bound_context_pack_id=task.input_context_pack_ref,
    )


def _context_pack(
    *,
    run_id: str = "run-hierarchy",
    context_pack_id: str = "pack-hierarchy",
) -> ContextPack:
    return ContextPack(
        context_pack_id=context_pack_id,
        run_id=run_id,
        requester_agent="MainAgent",
        target_agent="ResearchExpert",
        purpose="architecture-test",
        token_budget=2_000,
        facts=(),
        compression_policy_version="test-v1",
    )
