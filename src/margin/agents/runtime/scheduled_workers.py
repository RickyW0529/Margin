"""Declarative LangGraph workers and tools for scheduled research runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.registry import (
    scheduled_domain_agent_cards,
    scheduled_worker_agent_cards,
)
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
)
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.catalog import ToolCatalog, ToolHandler
from margin.agents.tools.langgraph_adapter import (
    LangGraphRuntimeContext,
    LangGraphToolAdapter,
)
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus, ToolSpec
from margin.core.hashing import stable_json_hash

SCHEDULE_INSPECT_DATA_TOOL = "schedule.inspect_data"
VALUATION_START_REFRESH_TOOL = "valuation.start_refresh"


class _ScheduledWorkerState(TypedDict, total=False):
    tool_input: dict[str, Any]
    planned_tool: dict[str, str]
    tool_status: str
    tool_output: dict[str, Any] | None
    audit_ref: str | None
    error_code: str | None
    retryable: bool
    observations: list[dict[str, Any]]


@dataclass(frozen=True)
class ScheduledArtifactDraft:
    """Artifact payload emitted from one authorized scheduled tool result."""

    artifact_id: str
    artifact_type: str
    payload_json: dict[str, Any]
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


ScheduledInputBuilder = Callable[
    [WorkerTaskRequest, WorkerExecutionContext],
    dict[str, Any],
]
ScheduledArtifactBuilder = Callable[
    [WorkerTaskRequest, WorkerExecutionContext, dict[str, Any]],
    tuple[ScheduledArtifactDraft, ...],
]
ScheduledToolHandlerFactory = Callable[[Any], ToolHandler]


@dataclass(frozen=True)
class ScheduledToolBinding:
    """Runtime implementation bound to a manifest-declared tool name."""

    tool_spec: ToolSpec
    tool_handler_factory: ScheduledToolHandlerFactory
    input_builder: ScheduledInputBuilder
    artifact_builder: ScheduledArtifactBuilder


@dataclass(frozen=True)
class ScheduledRuntimeComponents:
    """Manifest cards plus their bound executors and tools."""

    bindings: tuple[ScheduledToolBinding, ...]
    domain_cards: tuple[DomainAgentCard, ...]
    worker_cards: tuple[WorkerAgentCard, ...]
    executor_registry: ExecutorRegistry
    tool_catalog: ToolCatalog


class ScheduledLangGraphToolExecutor:
    """Execute one declaratively bound tool inside a small LangGraph workflow."""

    def __init__(
        self,
        *,
        binding: ScheduledToolBinding,
        checkpointer: Any | None = None,
    ) -> None:
        self._binding = binding
        self._checkpointer = checkpointer

    def execute(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionBundle:
        """Plan the declared tool, invoke it through ToolGateway, and observe output."""
        capability_token = context.capability_token
        if context.tool_gateway is None or capability_token is None:
            return _blocked_bundle(
                request,
                error_code="scheduled_worker_runtime_unavailable",
                summary="Scheduled worker requires ToolGateway and a capability token.",
            )
        graph: Any = StateGraph(_ScheduledWorkerState)
        adapter = LangGraphToolAdapter(
            tool_spec=self._binding.tool_spec,
            gateway=context.tool_gateway,
        )

        def plan_tool(_state: _ScheduledWorkerState) -> dict[str, Any]:
            return {
                "planned_tool": {
                    "tool_name": self._binding.tool_spec.tool_name,
                    "tool_version": self._binding.tool_spec.tool_version,
                }
            }

        def invoke_tool(state: _ScheduledWorkerState) -> dict[str, Any]:
            result = adapter.invoke(
                state["tool_input"],
                LangGraphRuntimeContext(
                    run_id=request.run_id,
                    worker_task_id=request.worker_task_id,
                    worker_agent=request.worker_agent,
                    capability_token=capability_token,
                    context_pack_id=request.input_context_pack_ref,
                    context_pack_hash=context.context_pack.content_hash,
                    idempotency_key=(
                        f"{request.idempotency_key}:{self._binding.tool_spec.tool_name}"
                    ),
                    deadline_ms=min(
                        request.deadline_ms,
                        self._binding.tool_spec.timeout_ms,
                    ),
                ),
            )
            return {
                "tool_status": result.status.value,
                "tool_output": result.output_json,
                "audit_ref": result.audit_ref,
                "error_code": result.error_code,
                "retryable": result.retryable,
            }

        def observe(state: _ScheduledWorkerState) -> dict[str, Any]:
            return {
                "observations": [
                    {
                        **state["planned_tool"],
                        "status": state.get("tool_status"),
                        "output": state.get("tool_output"),
                        "audit_ref": state.get("audit_ref"),
                        "error_code": state.get("error_code"),
                    }
                ]
            }

        graph.add_node("plan_tool", plan_tool)
        graph.add_node("invoke_tool", invoke_tool)
        graph.add_node("observe", observe)
        graph.add_edge(START, "plan_tool")
        graph.add_edge("plan_tool", "invoke_tool")
        graph.add_edge("invoke_tool", "observe")
        graph.add_edge("observe", END)
        compiled = graph.compile(checkpointer=self._checkpointer)
        try:
            state = compiled.invoke(
                {
                    "tool_input": self._binding.input_builder(request, context),
                    "observations": [],
                },
                config={
                    "configurable": {
                        "thread_id": f"{request.run_id}:{request.worker_task_id}",
                    }
                },
            )
        except Exception as exc:
            return _blocked_bundle(
                request,
                error_code=f"scheduled_worker_graph_failed:{type(exc).__name__}",
                summary="Scheduled worker LangGraph execution failed.",
            )
        return self._bundle_from_state(request, context, dict(state))

    def _bundle_from_state(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
        state: dict[str, Any],
    ) -> WorkerExecutionBundle:
        assert context.capability_token is not None
        tool_succeeded = state.get("tool_status") == ToolCallStatus.SUCCEEDED.value
        output = state.get("tool_output") or {}
        artifacts: list[ContextArtifact] = []
        if tool_succeeded:
            for draft in self._binding.artifact_builder(request, context, output):
                if draft.artifact_type not in context.capability_token.allowed_artifact_types:
                    continue
                artifacts.append(
                    make_context_artifact(
                        artifact_id=draft.artifact_id,
                        run_id=request.run_id,
                        artifact_type=draft.artifact_type,
                        producer_agent=request.worker_agent,
                        payload_json=draft.payload_json,
                        source_refs=draft.source_refs,
                        evidence_refs=draft.evidence_refs,
                    )
                )
        summary = str(
            output.get("safe_summary")
            or (
                f"{self._binding.tool_spec.tool_name} completed."
                if tool_succeeded
                else f"{self._binding.tool_spec.tool_name} was blocked."
            )
        )
        audit_ref = str(state.get("audit_ref") or "")
        if "worker_activity" in context.capability_token.allowed_artifact_types:
            artifacts.append(
                make_context_artifact(
                    artifact_id=(
                        f"ctx_{request.run_id}_{_safe_id(request.worker_task_id)}_activity"
                    ),
                    run_id=request.run_id,
                    artifact_type="worker_activity",
                    producer_agent=request.worker_agent,
                    payload_json={
                        "workflow_runtime": "langgraph",
                        "worker_agent": request.worker_agent,
                        "skill_id": request.skill_id,
                        "status": (
                            AgentExecutionStatus.SUCCEEDED.value
                            if tool_succeeded
                            else AgentExecutionStatus.BLOCKED.value
                        ),
                        "tool_call_count": 1,
                        "tool_calls": [self._binding.tool_spec.tool_name],
                        "observations": state.get("observations", []),
                        "error_code": state.get("error_code"),
                        "safe_summary": summary,
                    },
                    source_refs=(
                        "agent:scheduled-langgraph-worker",
                        *((audit_ref,) if audit_ref else ()),
                    ),
                )
            )
        produced_types = {artifact.artifact_type for artifact in artifacts}
        missing = tuple(
            artifact_type
            for artifact_type in request.required_output_types
            if artifact_type not in produced_types
        )
        succeeded = tool_succeeded and not missing
        if missing:
            summary = "Scheduled worker missing required artifacts: " + ", ".join(missing)
        return WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=request.run_id,
                domain_task_id=request.domain_task_id,
                worker_task_id=request.worker_task_id,
                worker_agent=request.worker_agent,
                skill_id=request.skill_id,
                status=(
                    AgentExecutionStatus.SUCCEEDED if succeeded else AgentExecutionStatus.BLOCKED
                ),
                output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
                audit_event_refs=((audit_ref,) if audit_ref else ()),
                error_code=(
                    None
                    if succeeded
                    else str(state.get("error_code") or "missing_required_artifacts")
                ),
                retryable=bool(state.get("retryable", False)),
                safe_summary=summary,
            ),
            artifacts=tuple(artifacts),
            answer=summary,
            table_rows=[],
        )


def build_scheduled_runtime_components(
    *,
    valuation_service: Any,
    checkpointer: Any | None = None,
) -> ScheduledRuntimeComponents:
    """Bind manifest cards to executable scheduled tool implementations."""
    bindings = scheduled_tool_bindings()
    domain_cards = scheduled_domain_agent_cards()
    worker_cards = scheduled_worker_agent_cards()
    bindings_by_tool = {binding.tool_spec.tool_name: binding for binding in bindings}
    if len(bindings_by_tool) != len(bindings):
        raise ValueError("scheduled tool bindings must have unique tool names")
    tool_catalog = ToolCatalog()
    executor_registry = ExecutorRegistry()
    for binding in bindings:
        tool_catalog.register(
            binding.tool_spec,
            binding.tool_handler_factory(valuation_service),
        )
    for worker_card in worker_cards:
        for skill in worker_card.skills:
            if skill.planned_only:
                continue
            binding = _binding_for_skill(skill, bindings_by_tool)
            executor_registry.register_spec(
                ExecutorSpec(
                    agent_name=worker_card.name,
                    skill_id=skill.skill_id,
                    executor=ScheduledLangGraphToolExecutor(
                        binding=binding,
                        checkpointer=checkpointer,
                    ),
                    runtime="langgraph",
                    required_tools=skill.tool_allowlist,
                    output_artifact_types=skill.output_artifact_types,
                    domain=worker_card.domain,
                )
            )
    return ScheduledRuntimeComponents(
        bindings=bindings,
        domain_cards=domain_cards,
        worker_cards=worker_cards,
        executor_registry=executor_registry,
        tool_catalog=tool_catalog,
    )


def scheduled_tool_bindings() -> tuple[ScheduledToolBinding, ...]:
    """Return implementations for tools referenced by the scheduled manifest."""
    return (
        ScheduledToolBinding(
            tool_spec=_inspect_data_tool_spec(),
            tool_handler_factory=_inspect_data_handler_factory,
            input_builder=_inspect_data_input,
            artifact_builder=_data_readiness_artifacts,
        ),
        ScheduledToolBinding(
            tool_spec=_valuation_refresh_tool_spec(),
            tool_handler_factory=_valuation_handler_factory,
            input_builder=_valuation_refresh_input,
            artifact_builder=_valuation_refresh_artifacts,
        ),
    )


def _binding_for_skill(
    skill: WorkerSkill,
    bindings_by_tool: dict[str, ScheduledToolBinding],
) -> ScheduledToolBinding:
    if len(skill.tool_allowlist) != 1:
        raise ValueError(f"scheduled skill {skill.skill_id} must declare exactly one tool")
    tool_name = skill.tool_allowlist[0]
    try:
        return bindings_by_tool[tool_name]
    except KeyError as exc:
        raise ValueError(
            f"scheduled skill {skill.skill_id} has no implementation for {tool_name}"
        ) from exc


def _inspect_data_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_name=SCHEDULE_INSPECT_DATA_TOOL,
        tool_version="v1",
        description="Inspect the resolved scheduled scope before research refresh.",
        owner_domain="data",
        input_schema_ref="schedule.inspect_data.input.v1",
        output_schema_ref="schedule.inspect_data.output.v1",
        input_schema={
            "type": "object",
            "required": ["scope_version_id", "universe", "schedule_id", "decision_at"],
            "properties": {
                "scope_version_id": {"type": "string", "minLength": 1},
                "universe": {"type": "string", "minLength": 1},
                "schedule_id": {"type": "string", "minLength": 1},
                "decision_at": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["ok", "status", "scope_version_id", "universe", "schedule_id"],
            "properties": {
                "ok": {"type": "boolean"},
                "status": {"type": "string"},
                "scope_version_id": {"type": "string"},
                "universe": {"type": "string"},
                "schedule_id": {"type": "string"},
            },
        },
        required_data_access=(DataAccessPolicy.READ_PROVIDER_STATUS,),
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.DATA_SYNC_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=30_000,
        max_output_bytes=32_000,
        allowed_runtimes=("langgraph",),
    )


def _valuation_refresh_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_name=VALUATION_START_REFRESH_TOOL,
        tool_version="v1",
        description="Start one idempotent valuation-discovery refresh.",
        owner_domain="quant",
        input_schema_ref="valuation.start_refresh.input.v1",
        output_schema_ref="valuation.start_refresh.output.v1",
        input_schema={
            "type": "object",
            "required": [
                "scope_version_id",
                "universe",
                "schedule_id",
                "decision_at",
                "idempotency_key",
                "metadata",
            ],
            "properties": {
                "scope_version_id": {"type": "string", "minLength": 1},
                "universe": {"type": "string", "minLength": 1},
                "schedule_id": {"type": "string", "minLength": 1},
                "decision_at": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": [
                "ok",
                "status",
                "valuation_refresh_run_id",
                "scope_version_id",
                "schedule_id",
            ],
            "properties": {
                "ok": {"type": "boolean"},
                "status": {"type": "string"},
                "valuation_refresh_run_id": {"type": "string"},
                "scope_version_id": {"type": "string"},
                "schedule_id": {"type": "string"},
            },
        },
        required_data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        required_write_policy=(
            ProductionWritePolicy.WRITE_ANALYSIS_MART,
            ProductionWritePolicy.WRITE_DASHBOARD_PROJECTION,
        ),
        required_tool_policy=(ToolPolicy.QUANT_TOOLS,),
        idempotent=True,
        mutates_state=True,
        timeout_ms=120_000,
        max_output_bytes=128_000,
        allowed_runtimes=("langgraph",),
    )


def _inspect_data_handler_factory(_valuation_service: Any) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        scope_version_id = str(request.input_json.get("scope_version_id") or "").strip()
        universe = str(request.input_json.get("universe") or "").strip()
        if not scope_version_id or not universe:
            return {
                "ok": False,
                "error": {
                    "code": "scheduled_scope_incomplete",
                    "message": "Resolved scope and universe are required.",
                },
            }
        return {
            "ok": True,
            "status": "ready_for_valuation_refresh",
            "scope_version_id": scope_version_id,
            "universe": universe,
            "schedule_id": str(request.input_json.get("schedule_id") or ""),
            "checked_at": str(request.input_json.get("decision_at") or ""),
            "safe_summary": "Scheduled data readiness inspection completed.",
        }

    return handler


def _valuation_handler_factory(valuation_service: Any) -> ToolHandler:
    def handler(request: ToolCallRequest) -> dict[str, Any]:
        input_json = request.input_json
        decision_at = _parse_datetime(input_json.get("decision_at"))
        metadata = input_json.get("metadata")
        resolved_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        response = valuation_service.start_refresh(
            scope_version_id=str(input_json.get("scope_version_id") or ""),
            decision_at=decision_at,
            idempotency_key=str(input_json.get("idempotency_key") or ""),
            metadata=resolved_metadata,
        )
        refresh_run_id = str(getattr(response, "run_id", "") or "")
        return {
            "ok": True,
            "status": "refresh_started",
            "valuation_refresh_run_id": refresh_run_id,
            "scope_version_id": str(input_json.get("scope_version_id") or ""),
            "universe": str(input_json.get("universe") or ""),
            "schedule_id": str(input_json.get("schedule_id") or ""),
            "decision_at": decision_at.isoformat(),
            "dashboard_projection": "expected_after_refresh",
            "metadata": resolved_metadata,
            "safe_summary": "Valuation refresh started through the authorized tool.",
        }

    return handler


def _inspect_data_input(
    _request: WorkerTaskRequest,
    context: WorkerExecutionContext,
) -> dict[str, Any]:
    metadata = _run_metadata(context)
    return {
        "scope_version_id": metadata.get("resolved_scope_version_id"),
        "universe": metadata.get("universe"),
        "schedule_id": metadata.get("schedule_id"),
        "decision_at": metadata.get("decision_at"),
    }


def _valuation_refresh_input(
    request: WorkerTaskRequest,
    context: WorkerExecutionContext,
) -> dict[str, Any]:
    metadata = _run_metadata(context)
    plan_metadata = metadata.get("plan_metadata")
    resolved_plan_metadata = (
        dict(plan_metadata) if isinstance(plan_metadata, dict) else {}
    )
    resolved_plan_metadata["input_artifacts"] = _input_artifact_views(request, context)
    return {
        "scope_version_id": metadata.get("resolved_scope_version_id"),
        "universe": metadata.get("universe"),
        "schedule_id": metadata.get("schedule_id"),
        "decision_at": metadata.get("decision_at"),
        "idempotency_key": metadata.get("valuation_idempotency_key"),
        "metadata": resolved_plan_metadata,
    }


def _data_readiness_artifacts(
    request: WorkerTaskRequest,
    _context: WorkerExecutionContext,
    output: dict[str, Any],
) -> tuple[ScheduledArtifactDraft, ...]:
    return (
        ScheduledArtifactDraft(
            artifact_id=f"ctx_{request.run_id}_l3_data_readiness",
            artifact_type="data_readiness",
            payload_json={
                **output,
                "worker_agent": request.worker_agent,
                "skill_id": request.skill_id,
                "worker_layer": "L3",
                "tool_name": SCHEDULE_INSPECT_DATA_TOOL,
            },
            source_refs=(
                f"schedule:{output.get('schedule_id', '')}",
                str(output.get("scope_version_id") or ""),
            ),
        ),
    )


def _valuation_refresh_artifacts(
    request: WorkerTaskRequest,
    _context: WorkerExecutionContext,
    output: dict[str, Any],
) -> tuple[ScheduledArtifactDraft, ...]:
    metadata = output.get("metadata")
    plan_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    refresh_payload = {
        **output,
        **plan_metadata,
        "worker_agent": request.worker_agent,
        "skill_id": request.skill_id,
        "worker_layer": "L3",
        "tool_name": VALUATION_START_REFRESH_TOOL,
    }
    refresh_run_id = str(output.get("valuation_refresh_run_id") or "")
    source_refs = (
        f"schedule:{output.get('schedule_id', '')}",
        refresh_run_id or "valuation_refresh",
    )
    return (
        ScheduledArtifactDraft(
            artifact_id=f"ctx_{request.run_id}_l3_valuation_refresh",
            artifact_type="valuation_refresh",
            payload_json=refresh_payload,
            source_refs=source_refs,
        ),
        ScheduledArtifactDraft(
            artifact_id=f"ctx_{request.run_id}_quant_result",
            artifact_type="quant_result",
            payload_json={
                "status": output.get("status"),
                "valuation_refresh_run_id": refresh_run_id,
                "scope_version_id": output.get("scope_version_id"),
                "universe": output.get("universe"),
                "tool_name": VALUATION_START_REFRESH_TOOL,
            },
            source_refs=source_refs,
        ),
    )


def _run_metadata(context: WorkerExecutionContext) -> dict[str, Any]:
    metadata = getattr(context.command, "metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


def _input_artifact_views(
    request: WorkerTaskRequest,
    context: WorkerExecutionContext,
) -> list[dict[str, Any]]:
    getter = getattr(context.context_store, "get_artifact", None)
    if not callable(getter):
        return []
    views: list[dict[str, Any]] = []
    for artifact_ref in request.input_artifact_refs:
        artifact = getter(artifact_ref)
        if not isinstance(artifact, ContextArtifact) or artifact.run_id != request.run_id:
            continue
        if artifact.payload_hash != stable_json_hash(artifact.payload_json):
            continue
        views.append(
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "producer_agent": artifact.producer_agent,
                "payload_hash": artifact.payload_hash,
                "payload_json": artifact.payload_json,
            }
        )
    return views


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _blocked_bundle(
    request: WorkerTaskRequest,
    *,
    error_code: str,
    summary: str,
) -> WorkerExecutionBundle:
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=request.worker_agent,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.BLOCKED,
            error_code=error_code,
            retryable=False,
            safe_summary=summary,
        ),
        artifacts=(),
        answer=summary,
        table_rows=[],
    )


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in value)
