"""Generic LangGraph worker that plans and executes authorized tools dynamically."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, model_validator

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextPack,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
)
from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.gateway import ToolGateway
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus, ToolSpec
from margin.core.hashing import stable_json_hash
from margin.research.llm import LLMProvider, strip_thinking_blocks


class WorkerLoopActionKind(StrEnum):
    """Actions available to the worker's structured planner."""

    TOOL = "tool"
    FINISH = "finish"
    BLOCK = "block"


class WorkerArtifactDraft(BaseModel):
    """Planner-proposed artifact restricted by the worker task contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class WorkerLoopAction(BaseModel):
    """One structured plan action emitted by the LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: WorkerLoopActionKind
    tool_name: str | None = None
    tool_version: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    answer: str = ""
    reason: str = ""
    retryable: bool = False
    artifacts: tuple[WorkerArtifactDraft, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> WorkerLoopAction:
        """Require the fields needed by the selected action."""
        if self.action is WorkerLoopActionKind.TOOL and not self.tool_name:
            raise ValueError("tool action requires tool_name")
        if self.action is WorkerLoopActionKind.FINISH and not (
            self.answer.strip() or self.artifacts
        ):
            raise ValueError("finish action requires answer or artifacts")
        if self.action is WorkerLoopActionKind.BLOCK and not self.reason.strip():
            raise ValueError("block action requires reason")
        return self


class WorkerLoopState(TypedDict, total=False):
    """Checkpoint-safe state for the generic worker graph."""

    task_goal: str
    context: dict[str, Any]
    observations: list[dict[str, Any]]
    planning_steps: int
    tool_calls: int
    action: dict[str, Any]
    pending_observation: dict[str, Any]
    terminal_status: str
    final_answer: str
    final_reason: str
    final_artifacts: list[dict[str, Any]]
    error_code: str | None
    retryable: bool


WORKER_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"enum": ["tool", "finish", "block"]},
        "tool_name": {"type": ["string", "null"]},
        "tool_version": {"type": ["string", "null"]},
        "tool_input": {"type": "object"},
        "answer": {"type": "string"},
        "reason": {"type": "string"},
        "retryable": {"type": "boolean"},
        "artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["artifact_type", "payload_json"],
                "properties": {
                    "artifact_type": {"type": "string"},
                    "payload_json": {"type": "object"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class _LoopRuntime:
    request: WorkerTaskRequest
    capability_token: CapabilityToken
    tool_catalog: ToolCatalog
    tool_gateway: ToolGateway
    llm_provider: LLMProvider
    deadline_at: float
    max_tool_calls: int
    max_planning_steps: int
    minimum_tool_calls: int
    artifact_tool_requirements: Mapping[str, tuple[str, ...]]
    context_pack_hash: str | None
    monotonic: Any


class LangGraphWorkerExecutor:
    """Execute arbitrary L3 tasks with an LLM-directed LangGraph tool loop.

    The planner sees only tools currently authorized by both ``ToolCatalog`` and
    ``CapabilityToken``. Tool handlers are never invoked directly; every call is
    routed through ``ToolGateway`` for authorization, schema checks, audit, and
    idempotency.
    """

    def __init__(
        self,
        *,
        tool_catalog: ToolCatalog,
        tool_gateway: ToolGateway | None = None,
        llm_provider: LLMProvider | None = None,
        checkpointer: Any | None = None,
        max_planning_steps: int = 32,
        minimum_tool_calls: int = 0,
        artifact_tool_requirements: Mapping[str, tuple[str, ...]] | None = None,
        monotonic: Any = time.monotonic,
    ) -> None:
        if max_planning_steps < 1:
            raise ValueError("max_planning_steps must be at least 1")
        if minimum_tool_calls < 0:
            raise ValueError("minimum_tool_calls cannot be negative")
        self._tool_catalog = tool_catalog
        self._tool_gateway = tool_gateway
        self._llm_provider = llm_provider
        self._checkpointer = checkpointer
        self._max_planning_steps = max_planning_steps
        self._minimum_tool_calls = minimum_tool_calls
        self._artifact_tool_requirements = dict(artifact_tool_requirements or {})
        self._monotonic = monotonic

    def execute(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext | None = None,
        *,
        capability_token: CapabilityToken | None = None,
        context_pack: ContextPack | None = None,
    ) -> WorkerExecutionBundle:
        """Run one WorkerTaskRequest to a finish or blocked terminal action."""
        token = capability_token or (context.capability_token if context is not None else None)
        gateway = self._tool_gateway or (context.tool_gateway if context is not None else None)
        llm_provider = self._llm_provider or (
            context.llm_provider_factory() if context is not None else None
        )
        resolved_context_pack = context_pack or (
            context.context_pack if context is not None else None
        )
        configuration_error = _configuration_error(
            request=request,
            capability_token=token,
            tool_gateway=gateway,
            llm_provider=llm_provider,
            context_pack=resolved_context_pack,
        )
        if configuration_error is not None:
            return _configuration_blocked_bundle(request, configuration_error)
        assert token is not None
        assert gateway is not None
        assert llm_provider is not None

        started_at = self._monotonic()
        runtime = _LoopRuntime(
            request=request,
            capability_token=token,
            tool_catalog=self._tool_catalog,
            tool_gateway=gateway,
            llm_provider=llm_provider,
            deadline_at=started_at + (request.deadline_ms / 1000),
            max_tool_calls=min(request.max_tool_calls, token.max_tool_calls),
            max_planning_steps=self._max_planning_steps,
            minimum_tool_calls=self._minimum_tool_calls,
            artifact_tool_requirements=self._artifact_tool_requirements,
            context_pack_hash=(
                resolved_context_pack.content_hash
                if resolved_context_pack is not None
                else None
            ),
            monotonic=self._monotonic,
        )
        graph = _build_worker_graph(runtime, checkpointer=self._checkpointer)
        initial_state: WorkerLoopState = {
            "task_goal": request.task_goal,
            "context": _context_payload(
                request,
                resolved_context_pack,
                input_artifacts=_load_input_artifacts(request, context),
            ),
            "observations": [],
            "planning_steps": 0,
            "tool_calls": 0,
            "action": {},
            "pending_observation": {},
            "terminal_status": "",
            "final_answer": "",
            "final_reason": "",
            "final_artifacts": [],
            "error_code": None,
            "retryable": False,
        }
        config = {
            "configurable": {
                "thread_id": f"{request.run_id}:{request.worker_task_id}",
                "checkpoint_ns": "langgraph-worker",
            },
            "recursion_limit": max(25, self._max_planning_steps * 4 + 8),
        }
        try:
            raw_state = graph.invoke(initial_state, config=config)
            state = dict(raw_state)
        except Exception as exc:
            state = dict(initial_state)
            state.update(
                _blocked_update(
                    reason="Worker graph execution failed.",
                    error_code=f"graph_execution_failed:{type(exc).__name__}",
                    retryable=True,
                )
            )
        return _bundle_from_terminal_state(runtime, state)


def _build_worker_graph(runtime: _LoopRuntime, *, checkpointer: Any | None) -> Any:
    graph: Any = StateGraph(WorkerLoopState)

    def plan(state: WorkerLoopState) -> dict[str, Any]:
        if state.get("terminal_status"):
            return {}
        if _deadline_exceeded(runtime):
            return _blocked_update(
                reason="Worker deadline exceeded before planning completed.",
                error_code="deadline_exceeded",
                retryable=True,
            )
        planning_steps = int(state.get("planning_steps", 0))
        if planning_steps >= runtime.max_planning_steps:
            return _blocked_update(
                reason="Worker planning step limit exceeded.",
                error_code="max_planning_steps_exceeded",
            )
        result = runtime.llm_provider.complete(
            _planning_prompt(runtime, state),
            response_schema=WORKER_ACTION_SCHEMA,
            temperature=0.0,
        )
        if _deadline_exceeded(runtime):
            return _blocked_update(
                reason="Worker deadline exceeded during planning.",
                error_code="deadline_exceeded",
                retryable=True,
                planning_steps=planning_steps + 1,
            )
        if not result.success:
            return _blocked_update(
                reason=result.error or "Worker planner failed.",
                error_code="llm_planning_failed",
                retryable=True,
                planning_steps=planning_steps + 1,
            )
        try:
            action = WorkerLoopAction.model_validate(result.output)
        except Exception as exc:
            return _blocked_update(
                reason="Worker planner returned an invalid action.",
                error_code=f"invalid_planner_action:{type(exc).__name__}",
                planning_steps=planning_steps + 1,
            )
        update: dict[str, Any] = {
            "planning_steps": planning_steps + 1,
            "action": action.model_dump(mode="json"),
        }
        if action.action is WorkerLoopActionKind.TOOL:
            if int(state.get("tool_calls", 0)) >= runtime.max_tool_calls:
                update.update(
                    _blocked_update(
                        reason="Worker tool-call budget exhausted.",
                        error_code="max_tool_calls_exceeded",
                    )
                )
            return update
        if action.action is WorkerLoopActionKind.FINISH:
            successful_tool_calls = sum(
                1
                for observation in state.get("observations", [])
                if observation.get("status") == ToolCallStatus.SUCCEEDED.value
            )
            if successful_tool_calls < runtime.minimum_tool_calls:
                update.update(
                    _blocked_update(
                        reason=(
                            "Worker finished before the required successful tool evidence "
                            "was collected."
                        ),
                        error_code="minimum_tool_calls_not_met",
                    )
                )
                return update
            update.update(
                {
                    "terminal_status": AgentExecutionStatus.SUCCEEDED.value,
                    "final_answer": strip_thinking_blocks(action.answer),
                    "final_reason": action.reason.strip(),
                    "final_artifacts": [
                        artifact.model_dump(mode="json") for artifact in action.artifacts
                    ],
                    "error_code": None,
                    "retryable": False,
                }
            )
            return update
        update.update(
            _blocked_update(
                reason=action.reason,
                error_code="planner_blocked",
                retryable=action.retryable,
            )
        )
        return update

    def invoke_tool(state: WorkerLoopState) -> dict[str, Any]:
        action = WorkerLoopAction.model_validate(state["action"])
        call_number = int(state.get("tool_calls", 0)) + 1
        if _deadline_exceeded(runtime):
            return {
                "tool_calls": call_number,
                "pending_observation": _local_observation(
                    action=action,
                    call_number=call_number,
                    status=ToolCallStatus.BLOCKED,
                    error_code="deadline_exceeded",
                ),
                **_blocked_update(
                    reason="Worker deadline exceeded before tool invocation.",
                    error_code="deadline_exceeded",
                    retryable=True,
                ),
            }
        tool_spec = _resolve_visible_tool(runtime, action)
        if tool_spec is None:
            return {
                "tool_calls": call_number,
                "pending_observation": _local_observation(
                    action=action,
                    call_number=call_number,
                    status=ToolCallStatus.BLOCKED,
                    error_code="tool_not_visible",
                ),
            }
        input_hash = stable_json_hash(action.tool_input)
        remaining_ms = max(1, int((runtime.deadline_at - runtime.monotonic()) * 1000))
        try:
            result = runtime.tool_gateway.call(
                ToolCallRequest(
                    tool_call_id=(
                        f"tc_{_safe_id(runtime.request.worker_task_id)}_{call_number}_"
                        f"{_safe_id(tool_spec.tool_name)}_{input_hash[:12]}"
                    ),
                    run_id=runtime.request.run_id,
                    task_id=runtime.request.worker_task_id,
                    caller_agent=runtime.request.worker_agent,
                    tool_name=tool_spec.tool_name,
                    tool_version=tool_spec.tool_version,
                    input_json=action.tool_input,
                    capability_token=runtime.capability_token,
                    context_pack_id=runtime.request.input_context_pack_ref,
                    context_pack_hash=runtime.context_pack_hash,
                    idempotency_key=(
                        f"{runtime.request.idempotency_key}:{call_number}:"
                        f"{tool_spec.tool_name}:{tool_spec.tool_version}:{input_hash}"
                    ),
                    deadline_ms=min(remaining_ms, tool_spec.timeout_ms),
                )
            )
            observation = {
                "call_number": call_number,
                "tool_name": tool_spec.tool_name,
                "tool_version": tool_spec.tool_version,
                "input_hash": input_hash,
                "status": result.status.value,
                "output": result.output_json,
                "audit_ref": result.audit_ref,
                "error_code": result.error_code,
                "retryable": result.retryable,
            }
        except Exception as exc:
            observation = _local_observation(
                action=action,
                call_number=call_number,
                status=ToolCallStatus.FAILED,
                error_code=f"tool_gateway_error:{type(exc).__name__}",
            )
        return {"tool_calls": call_number, "pending_observation": observation}

    def observe(state: WorkerLoopState) -> dict[str, Any]:
        observations = list(state.get("observations", ()))
        pending = state.get("pending_observation")
        if pending:
            observations.append(dict(pending))
        return {
            "observations": observations,
            "pending_observation": {},
            "action": {},
        }

    def finish(_state: WorkerLoopState) -> dict[str, Any]:
        return {}

    def block(_state: WorkerLoopState) -> dict[str, Any]:
        return {}

    graph.add_node("plan", plan)
    graph.add_node("invoke_tool", invoke_tool)
    graph.add_node("observe", observe)
    graph.add_node("finish", finish)
    graph.add_node("block", block)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        _route_after_plan,
        {
            "invoke_tool": "invoke_tool",
            "finish": "finish",
            "block": "block",
        },
    )
    graph.add_edge("invoke_tool", "observe")
    graph.add_edge("observe", "plan")
    graph.add_edge("finish", END)
    graph.add_edge("block", END)
    return graph.compile(checkpointer=checkpointer)


def _route_after_plan(state: WorkerLoopState) -> Literal["invoke_tool", "finish", "block"]:
    terminal_status = state.get("terminal_status")
    if terminal_status == AgentExecutionStatus.SUCCEEDED.value:
        return "finish"
    if terminal_status:
        return "block"
    return "invoke_tool"


def _planning_prompt(runtime: _LoopRuntime, state: WorkerLoopState) -> str:
    visible_tools = [_tool_prompt_item(spec) for spec in _visible_tools(runtime)]
    prompt_payload = {
        "task_goal": state.get("task_goal", ""),
        "context": state.get("context", {}),
        "observations": state.get("observations", []),
        "tool_calls_used": state.get("tool_calls", 0),
        "tool_calls_remaining": max(
            0,
            runtime.max_tool_calls - int(state.get("tool_calls", 0)),
        ),
        "minimum_tool_calls": runtime.minimum_tool_calls,
        "required_output_types": list(runtime.request.required_output_types),
        "visible_tools": visible_tools,
    }
    return "\n".join(
        (
            "You are an L3 WorkerAgent. Plan one next action at a time.",
            "Use only visible_tools. Never invent a tool name or call a tool outside ToolGateway.",
            "After every tool observation, reassess the task before choosing the next action.",
            "Choose finish only when the task can be answered from context and observations.",
            (
                "Choose block when evidence, permissions, inputs, or executable tools "
                "are insufficient."
            ),
            "For finish, return a concise answer and any task-required structured artifacts.",
            "Output JSON only and conform to the supplied action schema.",
            _bounded_json(prompt_payload, max_chars=max(4000, runtime.request.token_budget * 4)),
        )
    )


def _bundle_from_terminal_state(
    runtime: _LoopRuntime,
    state: dict[str, Any],
) -> WorkerExecutionBundle:
    succeeded = state.get("terminal_status") == AgentExecutionStatus.SUCCEEDED.value
    answer = strip_thinking_blocks(str(state.get("final_answer") or "")).strip()
    reason = str(state.get("final_reason") or "").strip()
    error_code = state.get("error_code")
    status = AgentExecutionStatus.SUCCEEDED if succeeded else AgentExecutionStatus.BLOCKED
    audit_refs = tuple(
        str(observation["audit_ref"])
        for observation in state.get("observations", [])
        if observation.get("audit_ref")
    )
    artifacts: list[ContextArtifact] = []
    if succeeded:
        artifacts.extend(
            _planner_artifacts(
                runtime,
                state.get("final_artifacts", []),
                observations=state.get("observations", []),
            )
        )
    if (answer or (not succeeded and reason)) and _artifact_type_allowed(runtime, "qna_answer"):
        artifacts.append(
            make_context_artifact(
                artifact_id=_artifact_id(runtime.request, "qna_answer", len(artifacts)),
                run_id=runtime.request.run_id,
                artifact_type="qna_answer",
                producer_agent=runtime.request.worker_agent,
                payload_json={
                    "answer": answer or reason,
                    "language": str(runtime.request.constraints.get("language") or "zh"),
                },
                source_refs=("agent:langgraph-worker",),
            )
        )
    produced_types = {artifact.artifact_type for artifact in artifacts}
    if _artifact_type_allowed(runtime, "worker_activity"):
        produced_types.add("worker_activity")
    missing_types = tuple(
        artifact_type
        for artifact_type in runtime.request.required_output_types
        if artifact_type not in produced_types
    )
    if succeeded and missing_types:
        status = AgentExecutionStatus.BLOCKED
        error_code = "missing_required_artifacts"
        reason = "Worker did not produce required artifacts: " + ", ".join(missing_types)
        answer = ""
    if succeeded and not produced_types:
        status = AgentExecutionStatus.BLOCKED
        error_code = "no_allowed_output_artifacts"
        reason = "Worker has no authorized output artifact type."
        answer = ""
    if _artifact_type_allowed(runtime, "worker_activity"):
        artifacts.append(
            make_context_artifact(
                artifact_id=_artifact_id(
                    runtime.request,
                    "worker_activity",
                    len(artifacts),
                ),
                run_id=runtime.request.run_id,
                artifact_type="worker_activity",
                producer_agent=runtime.request.worker_agent,
                payload_json={
                    "workflow_runtime": "langgraph",
                    "worker_agent": runtime.request.worker_agent,
                    "skill_id": runtime.request.skill_id,
                    "status": status.value,
                    "planning_steps": int(state.get("planning_steps", 0)),
                    "tool_call_count": int(state.get("tool_calls", 0)),
                    "visible_tools": [
                        {"tool_name": spec.tool_name, "tool_version": spec.tool_version}
                        for spec in _visible_tools(runtime)
                    ],
                    "observations": _artifact_safe_value(
                        list(state.get("observations", []))
                    ),
                    "error_code": error_code,
                    "safe_summary": answer or reason,
                },
                source_refs=("agent:langgraph-worker", *audit_refs),
            )
        )
    result = WorkerTaskResult(
        run_id=runtime.request.run_id,
        domain_task_id=runtime.request.domain_task_id,
        worker_task_id=runtime.request.worker_task_id,
        worker_agent=runtime.request.worker_agent,
        skill_id=runtime.request.skill_id,
        status=status,
        output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
        audit_event_refs=audit_refs,
        error_code=str(error_code) if error_code else None,
        retryable=bool(state.get("retryable", False)),
        safe_summary=(answer or reason or "Worker completed without a user-visible summary.")[
            :1000
        ],
    )
    return WorkerExecutionBundle(
        result=result,
        artifacts=tuple(artifacts),
        answer=answer or None,
        table_rows=_table_rows(artifacts),
    )


def _planner_artifacts(
    runtime: _LoopRuntime,
    raw_artifacts: list[dict[str, Any]],
    *,
    observations: list[dict[str, Any]],
) -> list[ContextArtifact]:
    allowed_types = set(runtime.capability_token.allowed_artifact_types)
    requested_types = set(runtime.request.required_output_types)
    artifacts: list[ContextArtifact] = []
    for raw_artifact in raw_artifacts:
        try:
            draft = WorkerArtifactDraft.model_validate(raw_artifact)
        except Exception:
            continue
        if draft.artifact_type in {"qna_answer", "worker_activity"}:
            continue
        if draft.artifact_type not in requested_types:
            continue
        if draft.artifact_type not in allowed_types:
            continue
        required_tools = runtime.artifact_tool_requirements.get(
            draft.artifact_type,
            (),
        )
        supporting_observations = tuple(
            observation
            for observation in observations
            if observation.get("status") == ToolCallStatus.SUCCEEDED.value
            and (
                not required_tools
                or str(observation.get("tool_name") or "") in required_tools
            )
        )
        if required_tools and not supporting_observations:
            continue
        audit_refs = tuple(
            str(observation["audit_ref"])
            for observation in supporting_observations
            if observation.get("audit_ref")
        )
        payload_json = draft.payload_json
        if required_tools:
            payload_json = {
                "tool_results": [
                    {
                        "tool_name": observation.get("tool_name"),
                        "tool_version": observation.get("tool_version"),
                        "output": _artifact_safe_value(observation.get("output")),
                        "audit_ref": observation.get("audit_ref"),
                    }
                    for observation in supporting_observations
                ]
            }
        artifacts.append(
            make_context_artifact(
                artifact_id=_artifact_id(
                    runtime.request,
                    draft.artifact_type,
                    len(artifacts),
                ),
                run_id=runtime.request.run_id,
                artifact_type=draft.artifact_type,
                producer_agent=runtime.request.worker_agent,
                payload_json=payload_json,
                source_refs=tuple(
                    dict.fromkeys(
                        (*draft.source_refs, "agent:langgraph-worker", *audit_refs)
                    )
                ),
                evidence_refs=draft.evidence_refs,
            )
        )
    return artifacts


def _configuration_error(
    *,
    request: WorkerTaskRequest,
    capability_token: CapabilityToken | None,
    tool_gateway: ToolGateway | None,
    llm_provider: LLMProvider | None,
    context_pack: ContextPack | None,
) -> tuple[str, str] | None:
    if capability_token is None:
        return "capability_token_unavailable", "Worker capability token is unavailable."
    if capability_token.token_id != request.capability_token_ref:
        return "capability_token_mismatch", "Worker capability token does not match the task."
    if capability_token.run_id != request.run_id:
        return "capability_run_mismatch", "Worker capability token belongs to another run."
    if capability_token.issued_to != request.worker_agent:
        return "capability_recipient_mismatch", "Worker capability token has another recipient."
    if (
        capability_token.bound_task_id is not None
        and capability_token.bound_task_id != request.worker_task_id
    ):
        return "capability_task_mismatch", "Worker capability token is bound to another task."
    if (
        capability_token.bound_context_pack_id is not None
        and capability_token.bound_context_pack_id != request.input_context_pack_ref
    ):
        return (
            "capability_context_mismatch",
            "Worker capability token is bound to another context pack.",
        )
    if capability_token.bound_context_pack_hash is not None and (
        context_pack is None
        or context_pack.content_hash != capability_token.bound_context_pack_hash
    ):
        return (
            "capability_context_hash_mismatch",
            "Worker capability token is bound to different context content.",
        )
    if tool_gateway is None:
        return "tool_gateway_unavailable", "Worker ToolGateway is unavailable."
    if llm_provider is None:
        return "llm_provider_unavailable", "Worker LLM provider is unavailable."
    return None


def _configuration_blocked_bundle(
    request: WorkerTaskRequest,
    error: tuple[str, str],
) -> WorkerExecutionBundle:
    error_code, summary = error
    activity = make_context_artifact(
        artifact_id=_artifact_id(request, "worker_activity", 0),
        run_id=request.run_id,
        artifact_type="worker_activity",
        producer_agent=request.worker_agent,
        payload_json={
            "workflow_runtime": "langgraph",
            "worker_agent": request.worker_agent,
            "skill_id": request.skill_id,
            "status": AgentExecutionStatus.BLOCKED.value,
            "tool_call_count": 0,
            "observations": [],
            "error_code": error_code,
            "safe_summary": summary,
        },
        source_refs=("agent:langgraph-worker",),
    )
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=request.worker_agent,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.BLOCKED,
            output_artifact_refs=(activity.artifact_id,),
            error_code=error_code,
            retryable=False,
            safe_summary=summary,
        ),
        artifacts=(activity,),
        answer=None,
        table_rows=[],
    )


def _blocked_update(
    *,
    reason: str,
    error_code: str,
    retryable: bool = False,
    planning_steps: int | None = None,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "terminal_status": AgentExecutionStatus.BLOCKED.value,
        "final_answer": "",
        "final_reason": reason.strip() or "Worker execution blocked.",
        "final_artifacts": [],
        "error_code": error_code,
        "retryable": retryable,
    }
    if planning_steps is not None:
        update["planning_steps"] = planning_steps
    return update


def _resolve_visible_tool(runtime: _LoopRuntime, action: WorkerLoopAction) -> ToolSpec | None:
    candidates = [
        spec
        for spec in _visible_tools(runtime)
        if spec.tool_name == action.tool_name
        and (action.tool_version is None or spec.tool_version == action.tool_version)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda spec: spec.tool_version, reverse=True)[0]


def _visible_tools(runtime: _LoopRuntime) -> tuple[ToolSpec, ...]:
    return runtime.tool_catalog.visible_specs(runtime.capability_token)


def _artifact_type_allowed(runtime: _LoopRuntime, artifact_type: str) -> bool:
    return artifact_type in runtime.capability_token.allowed_artifact_types


def _tool_prompt_item(spec: ToolSpec) -> dict[str, Any]:
    return {
        "tool_name": spec.tool_name,
        "tool_version": spec.tool_version,
        "description": spec.description,
        "input_schema_ref": spec.input_schema_ref,
        "input_schema": spec.input_schema,
        "output_schema_ref": spec.output_schema_ref,
        "output_schema": spec.output_schema,
        "mutates_state": spec.mutates_state,
    }


def _local_observation(
    *,
    action: WorkerLoopAction,
    call_number: int,
    status: ToolCallStatus,
    error_code: str,
) -> dict[str, Any]:
    return {
        "call_number": call_number,
        "tool_name": action.tool_name,
        "tool_version": action.tool_version,
        "input_hash": stable_json_hash(action.tool_input),
        "status": status.value,
        "output": None,
        "audit_ref": None,
        "error_code": error_code,
        "retryable": False,
    }


def _context_payload(
    request: WorkerTaskRequest,
    context_pack: ContextPack | None,
    *,
    input_artifacts: tuple[ContextArtifact, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any]
    if context_pack is None:
        payload = {
            "context_pack_ref": request.input_context_pack_ref,
            "input_artifact_refs": list(request.input_artifact_refs),
        }
    else:
        payload = {
            "context_pack_ref": context_pack.context_pack_id,
            "input_artifact_refs": list(
                dict.fromkeys(
                    (*context_pack.included_artifact_refs, *request.input_artifact_refs)
                )
            ),
            "purpose": context_pack.purpose,
            "facts": [fact.model_dump(mode="json") for fact in context_pack.facts],
            "included_artifact_refs": list(context_pack.included_artifact_refs),
            "included_capsule_refs": list(context_pack.included_capsule_refs),
            "evidence_refs": list(context_pack.evidence_refs),
            "source_refs": list(context_pack.source_refs),
            "omissions": [item.model_dump(mode="json") for item in context_pack.omissions],
        }
    payload["input_artifacts"] = _bounded_artifact_views(
        input_artifacts,
        max_chars=max(2_000, min(40_000, request.token_budget * 4)),
    )
    return payload


def _load_input_artifacts(
    request: WorkerTaskRequest,
    context: WorkerExecutionContext | None,
) -> tuple[ContextArtifact, ...]:
    if context is None:
        return ()
    getter = getattr(context.context_store, "get_artifact", None)
    if not callable(getter):
        return ()
    artifacts: list[ContextArtifact] = []
    for artifact_ref in request.input_artifact_refs:
        artifact = getter(artifact_ref)
        if not isinstance(artifact, ContextArtifact):
            continue
        if artifact.run_id != request.run_id:
            continue
        if artifact.payload_hash != stable_json_hash(artifact.payload_json):
            continue
        artifacts.append(artifact)
    return tuple(artifacts)


def _bounded_artifact_views(
    artifacts: tuple[ContextArtifact, ...],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    remaining = max_chars
    for artifact in artifacts:
        view: dict[str, Any] = {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "producer_agent": artifact.producer_agent,
            "payload_hash": artifact.payload_hash,
            "payload_json": _artifact_safe_value(artifact.payload_json),
            "source_refs": list(artifact.source_refs),
            "evidence_refs": list(artifact.evidence_refs),
        }
        encoded = json.dumps(view, ensure_ascii=False, default=str)
        if len(encoded) > remaining:
            view["payload_json"] = {
                "truncated": True,
                "preview": _bounded_json(
                    view["payload_json"],
                    max_chars=max(256, min(4_000, remaining)),
                ),
            }
            encoded = json.dumps(view, ensure_ascii=False, default=str)
        if len(encoded) > remaining:
            break
        views.append(view)
        remaining -= len(encoded)
    return views


def _artifact_id(request: WorkerTaskRequest, artifact_type: str, index: int) -> str:
    return (
        f"ctx_{_safe_id(request.run_id)}_{_safe_id(request.worker_task_id)}_"
        f"{_safe_id(artifact_type)}_{index}"
    )


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
    return normalized or "item"


def _deadline_exceeded(runtime: _LoopRuntime) -> bool:
    return runtime.monotonic() >= runtime.deadline_at


def _bounded_json(value: Any, *, max_chars: int) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(payload) <= max_chars:
        return payload
    return payload[: max(0, max_chars - 32)] + '..."truncated":true}'


def _artifact_safe_value(value: Any, *, key: str = "") -> Any:
    """Remove potentially large source/code payloads from persistent artifacts."""
    if key.lower() in {"content", "stdout", "stderr", "unified"}:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        return {
            "redacted": True,
            "sha256": stable_json_hash(value),
            "size_bytes": len(encoded),
        }
    if isinstance(value, dict):
        return {
            item_key: _artifact_safe_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_artifact_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_artifact_safe_value(item) for item in value]
    return value


def _table_rows(artifacts: list[ContextArtifact]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.artifact_type != "analysis_table":
            continue
        rows.extend(
            item for item in artifact.payload_json.get("rows", ()) if isinstance(item, dict)
        )
    return rows


# Concise aliases for registry wiring and tests.
DynamicLangGraphWorker = LangGraphWorkerExecutor
LangGraphToolWorker = LangGraphWorkerExecutor
