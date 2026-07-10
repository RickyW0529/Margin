"""Default WorkerAgent executor adapters for user Q&A runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from margin.agent_runtime.context_store import ContextArtifact, make_context_artifact
from margin.agents.context.readiness import CandidateLoadResult, ReadinessStatus
from margin.agents.context.turn_context import ResolvedTurnContext, resolve_turn_context
from margin.agents.protocol.models import AgentExecutionStatus, WorkerTaskRequest, WorkerTaskResult
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
)
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus
from margin.agents.workers.data_question_worker import DataQuestionWorker
from margin.research.llm import strip_thinking_blocks


class DataQuestionWorkerExecutor:
    """Adapter for the existing DataQuestionWorker implementation."""

    def __init__(self, worker: DataQuestionWorker | None) -> None:
        self._worker = worker

    def execute(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionBundle:
        """Execute DataQuestionWorker through the registry path."""
        if self._worker is None:
            return _blocked_worker_bundle(
                request,
                error_code="warehouse_repository_unavailable",
                summary="DataQuestionWorker requires a warehouse repository.",
            )
        worker_inputs = financial_metric_worker_inputs(
            current_user_message=context.command.message,
            planner_worker_inputs=request.constraints.get("worker_inputs"),
            resolved_turn_context=context.command.resolved_turn_context,
        )
        if worker_inputs is None:
            return _financial_metric_clarification_bundle(
                request,
                command=context.command,
            )
        try:
            analysis = self._worker.answer_financial_metric(
                run_id=context.command.run_id,
                message=context.command.message,
                conversation_context=(),
                worker_inputs=worker_inputs,
                chart_type=worker_inputs["chart_type"],
                tool_gateway=context.tool_gateway,
                capability_token=context.capability_token,
                context_pack_id=context.context_pack.context_pack_id,
                context_pack_hash=context.context_pack.content_hash,
                worker_task_id=request.worker_task_id,
                idempotency_key=request.idempotency_key,
            )
        except RuntimeError as exc:
            return _blocked_worker_bundle(
                request,
                error_code="data_question_worker_tool_error",
                summary=str(exc),
            )
        if analysis is None:
            return _blocked_worker_bundle(
                request,
                error_code="data_question_worker_no_answer",
                summary="DataQuestionWorker could not answer the task.",
            )
        answer_artifact = qna_answer_artifact(
            run_id=context.command.run_id,
            answer=analysis.answer,
            language=context.command.language,
            producer_agent=request.worker_agent,
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
                run_id=request.run_id,
                domain_task_id=request.domain_task_id,
                worker_task_id=request.worker_task_id,
                worker_agent=request.worker_agent,
                skill_id=request.skill_id,
                status=AgentExecutionStatus.SUCCEEDED,
                output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
                audit_event_refs=analysis.audit_event_refs,
                safe_summary="DataQuestionWorker produced analysis artifacts.",
            ),
            artifacts=artifacts,
            answer=analysis.answer,
            table_rows=analysis.table_rows,
        )


def financial_metric_worker_inputs(
    *,
    current_user_message: str,
    planner_worker_inputs: object | None,
    resolved_turn_context: ResolvedTurnContext | None = None,
) -> dict[str, Any] | None:
    """Return canonical DataQuestionWorker inputs from resolved user state.

    The planner may choose the worker, but never supplies lookup keys. This
    compatibility entry point resolves an isolated current turn; the runtime
    passes its persisted ``ResolvedTurnContext`` via the overload below.
    """
    del planner_worker_inputs
    context = resolved_turn_context or resolve_turn_context(current_user_message)
    return context.financial_metric_worker_inputs()


def _financial_metric_clarification_bundle(
    request: WorkerTaskRequest,
    *,
    command: Any,
) -> WorkerExecutionBundle:
    """Return a successful, non-fabricated answer for invalid/stale metric turns."""
    answer = (
        "我没有识别到当前这句话里的可执行财务指标查询。请直接输入“标的 + 指标”，"
        "例如：中国平安 ROE。这个回答只说明输入缺口，不构成投资建议。"
    )
    table_artifact = make_context_artifact(
        artifact_id=f"ctx_{command.run_id}_{request.worker_task_id}_metric_input_table",
        run_id=command.run_id,
        artifact_type="analysis_table",
        producer_agent=request.worker_agent,
        payload_json={"columns": [], "rows": [], "input_valid": False},
        source_refs=("agent:v1:user_qna",),
    )
    chart_artifact = make_context_artifact(
        artifact_id=f"ctx_{command.run_id}_{request.worker_task_id}_metric_input_chart",
        run_id=command.run_id,
        artifact_type="chart_spec",
        producer_agent=request.worker_agent,
        payload_json={
            "chart_type": "line",
            "title": "财务指标趋势",
            "x_field": "date",
            "y_field": "value",
            "unit": "",
            "series": [],
            "input_valid": False,
        },
        source_refs=("agent:v1:user_qna",),
    )
    image_artifact = make_context_artifact(
        artifact_id=f"ctx_{command.run_id}_{request.worker_task_id}_metric_input_image",
        run_id=command.run_id,
        artifact_type="visualization_image",
        producer_agent=request.worker_agent,
        payload_json={
            "image_format": "svg",
            "chart_type": "line",
            "title": "财务指标趋势",
            "svg": (
                "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='220'>"
                "<rect width='100%' height='100%' fill='white'/>"
                "<text x='24' y='110' font-size='16'>未识别到标的和指标</text>"
                "</svg>"
            ),
            "input_valid": False,
        },
        source_refs=("agent:v1:user_qna",),
    )
    metric_artifact = make_context_artifact(
        artifact_id=f"ctx_{command.run_id}_{request.worker_task_id}_metric_input_latest",
        run_id=command.run_id,
        artifact_type="computed_metric",
        producer_agent=request.worker_agent,
        payload_json={
            "indicator_id": None,
            "label": None,
            "latest_value": None,
            "unit": None,
            "input_valid": False,
        },
        source_refs=("agent:v1:user_qna",),
    )
    activity_artifact = make_context_artifact(
        artifact_id=f"ctx_{command.run_id}_{request.worker_task_id}_metric_input_activity",
        run_id=command.run_id,
        artifact_type="worker_activity",
        producer_agent=request.worker_agent,
        payload_json={
            "analysis_text": command.message,
            "input_valid": False,
            "error_code": "financial_metric_input_not_recognized",
            "tool_calls": [],
        },
        source_refs=("agent:v1:user_qna",),
    )
    answer_artifact = qna_answer_artifact(
        run_id=command.run_id,
        answer=answer,
        language=command.language,
        producer_agent=request.worker_agent,
    )
    artifacts = (
        table_artifact,
        metric_artifact,
        chart_artifact,
        image_artifact,
        activity_artifact,
        answer_artifact,
    )
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=request.worker_agent,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.SUCCEEDED,
            output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
            safe_summary="DataQuestionWorker rejected stale or incomplete metric inputs.",
        ),
        artifacts=artifacts,
        answer=answer,
        table_rows=[],
    )


class GeneralQnaWorkflowState(TypedDict, total=False):
    """State carried through GeneralQnaWorker's LangGraph workflow."""

    request: WorkerTaskRequest
    context: WorkerExecutionContext
    table_artifact: ContextArtifact
    table_rows: list[dict[str, Any]]
    answer: str
    answer_artifact: ContextArtifact
    bundle: WorkerExecutionBundle
    audit_event_refs: tuple[str, ...]
    node_trace: tuple[str, ...]


class GeneralQnaWorkerExecutor:
    """Adapter for context-bound general Q&A answers."""

    def __init__(
        self,
        *,
        llm_provider_factory: Any,
    ) -> None:
        self._llm_provider_factory = llm_provider_factory
        self._graph = self._build_graph()

    def execute(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionBundle:
        """Execute GeneralQnaWorker through the registry path."""
        final_state = self._graph.invoke(
            GeneralQnaWorkflowState(
                request=request,
                context=context,
                node_trace=(),
            )
        )
        bundle = final_state.get("bundle")
        if not isinstance(bundle, WorkerExecutionBundle):
            raise RuntimeError("GeneralQnaWorker graph did not produce a bundle")
        return bundle

    def _build_graph(self) -> Any:
        """Compile the fixed internal LangGraph workflow once per executor."""
        graph = StateGraph(GeneralQnaWorkflowState)
        graph.add_node("load_candidates", self._load_candidates_node)
        graph.add_node("generate_answer", self._generate_answer_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "load_candidates")
        graph.add_edge("load_candidates", "generate_answer")
        graph.add_edge("generate_answer", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _load_candidates_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        request = state["request"]
        context = state["context"]
        table_artifact, table_rows, audit_event_refs = (
            self._build_candidate_table_artifact(request, context)
        )
        return {
            "table_artifact": table_artifact,
            "table_rows": table_rows,
            "audit_event_refs": audit_event_refs,
            "node_trace": (*state.get("node_trace", ()), "load_candidates"),
        }

    def _generate_answer_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        context = state["context"]
        answer = self._answer_with_llm(
            command=context.command,
            context_pack=context.context_pack,
            table_rows=state["table_rows"],
        )
        return {
            "answer": answer,
            "node_trace": (*state.get("node_trace", ()), "generate_answer"),
        }

    def _finalize_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        request = state["request"]
        context = state["context"]
        table_artifact = state["table_artifact"]
        table_rows = state["table_rows"]
        answer = state["answer"]
        answer_artifact = qna_answer_artifact(
            run_id=context.command.run_id,
            answer=answer,
            language=context.command.language,
            producer_agent=request.worker_agent,
        )
        artifacts = (table_artifact, answer_artifact)
        bundle = WorkerExecutionBundle(
            result=WorkerTaskResult(
                run_id=request.run_id,
                domain_task_id=request.domain_task_id,
                worker_task_id=request.worker_task_id,
                worker_agent=request.worker_agent,
                skill_id=request.skill_id,
                status=AgentExecutionStatus.SUCCEEDED,
                output_artifact_refs=tuple(artifact.artifact_id for artifact in artifacts),
                audit_event_refs=state.get("audit_event_refs", ()),
                safe_summary="GeneralQnaWorker produced a context-bound answer.",
            ),
            artifacts=artifacts,
            answer=answer,
            table_rows=table_rows,
        )
        return {
            "answer_artifact": answer_artifact,
            "bundle": bundle,
            "node_trace": (*state.get("node_trace", ()), "finalize"),
        }

    def _build_candidate_table_artifact(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
    ) -> tuple[ContextArtifact, list[dict[str, Any]], tuple[str, ...]]:
        """Read dashboard candidates and store a table artifact."""
        command = context.command
        load_result = self._load_candidate_rows(request, context)
        rows = list(load_result.rows)
        artifact = make_context_artifact(
            artifact_id=f"ctx_{command.run_id}_dashboard_candidates",
            run_id=command.run_id,
            artifact_type="analysis_table",
            producer_agent="GeneralQnaWorker",
            payload_json={
                "scope_version_id": command.scope_version_id,
                "universe": command.universe,
                "status": load_result.status,
                "error_code": load_result.error_code,
                "retryable": load_result.retryable,
                "safe_summary": load_result.safe_summary,
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
        return artifact, rows, ((load_result.audit_ref,) if load_result.audit_ref else ())

    def _load_candidate_rows(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext,
    ) -> CandidateLoadResult:
        """Load a compact dashboard candidate table without exposing raw internals."""
        command = context.command
        if context.tool_gateway is not None and context.capability_token is not None:
            try:
                result = context.tool_gateway.call(
                    ToolCallRequest(
                        tool_call_id=f"tc_{command.run_id}_dashboard_read_candidates",
                        run_id=command.run_id,
                        task_id=request.worker_task_id,
                        caller_agent=request.worker_agent,
                        tool_name="dashboard.read_candidates",
                        tool_version="v1",
                        input_json={
                            "scope_version_id": command.scope_version_id,
                            "universe": command.universe,
                            "limit": 10,
                        },
                        capability_token=context.capability_token,
                        context_pack_id=context.context_pack.context_pack_id,
                        context_pack_hash=context.context_pack.content_hash,
                        idempotency_key=(
                            f"{request.idempotency_key}:dashboard.read_candidates"
                        ),
                        deadline_ms=30_000,
                    )
                )
            except Exception as exc:
                return CandidateLoadResult(
                    status=ReadinessStatus.ERROR,
                    error_code=type(exc).__name__,
                    retryable=True,
                    safe_summary="Dashboard candidate source failed to load.",
                )
            if result.status is not ToolCallStatus.SUCCEEDED or result.output_json is None:
                return CandidateLoadResult(
                    status=ReadinessStatus.ERROR,
                    error_code=result.error_code or "dashboard_tool_failed",
                    retryable=result.retryable,
                    safe_summary="Dashboard candidate source failed to load.",
                )
            return _candidate_load_result_from_tool_output(result.output_json).model_copy(
                update={"audit_ref": result.audit_ref}
            )
        return CandidateLoadResult(
            status=ReadinessStatus.ERROR,
            error_code="tool_gateway_unavailable",
            retryable=False,
            safe_summary="Dashboard ToolGateway is required for GeneralQnaWorker.",
        )

    def _answer_with_llm(
        self,
        *,
        command: Any,
        context_pack: Any,
        table_rows: list[dict[str, Any]],
    ) -> str:
        """Generate a user answer from approved context only."""
        prompt = build_user_answer_prompt(
            command=command,
            context_pack=context_pack,
            table_rows=table_rows,
        )
        result = self._llm_provider_factory().complete(prompt, temperature=0.0)
        if not result.success:
            raise RuntimeError(result.error or "LLM completion failed")
        answer = strip_thinking_blocks(
            result.raw_response or str(result.output.get("content", ""))
        )
        if not answer:
            raise RuntimeError("LLM returned an empty answer")
        return answer


def qna_answer_artifact(
    *,
    run_id: str,
    answer: str,
    language: str,
    producer_agent: str,
) -> ContextArtifact:
    """Return a qna_answer artifact."""
    return make_context_artifact(
        artifact_id=f"ctx_{run_id}_qna_answer_{_safe_agent_suffix(producer_agent)}",
        run_id=run_id,
        artifact_type="qna_answer",
        producer_agent=producer_agent,
        payload_json={"answer": answer, "language": language},
        source_refs=("agent:v1:user_qna",),
    )


def _candidate_load_result_from_tool_output(output: dict[str, Any]) -> CandidateLoadResult:
    status_value = str(output.get("status") or ReadinessStatus.UNKNOWN)
    try:
        status = ReadinessStatus(status_value)
    except ValueError:
        status = ReadinessStatus.UNKNOWN
    as_of_raw = output.get("as_of")
    as_of = (
        as_of_raw
        if isinstance(as_of_raw, datetime)
        else datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))
        if as_of_raw
        else None
    )
    rows = tuple(
        row
        for row in output.get("rows", ())
        if isinstance(row, dict)
    )
    return CandidateLoadResult(
        status=status,
        rows=rows,
        as_of=as_of,
        safe_summary=str(output.get("safe_summary") or ""),
    )


def build_user_answer_prompt(
    *,
    command: Any,
    context_pack: Any,
    table_rows: list[dict[str, Any]],
) -> str:
    """Build the final user-answer prompt for GeneralQnaWorker."""
    data_status_facts = [
        {
            "subject_id": fact.subject_id,
            "statement": fact.statement,
            "value_json": fact.value_json,
        }
        for fact in context_pack.facts
        if fact.fact_type == "data_status"
    ]
    return "\n".join(
        (
            "你是 Margin 的用户问答 Worker。只能基于给定上下文和候选表回答。",
            f"language={command.language}",
            f"user_message={command.message}",
            f"context_pack_ref={context_pack.context_pack_id}",
            f"included_chat_summary_ref={context_pack.included_chat_summary_ref}",
            "data_status_facts=" + repr(data_status_facts),
            "dashboard_candidate_rows=" + repr(table_rows),
            "如果候选为空，必须说明当前 Dashboard 候选为空或不可用，不能编造。",
        )
    )


def _blocked_worker_bundle(
    request: WorkerTaskRequest,
    *,
    error_code: str,
    summary: str,
) -> WorkerExecutionBundle:
    """Return a blocked worker bundle without artifacts."""
    return WorkerExecutionBundle(
        result=WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=request.worker_agent,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.BLOCKED,
            error_code=error_code,
            retryable=True,
            safe_summary=summary,
        ),
        artifacts=(),
        answer=None,
        table_rows=[],
    )


def _safe_agent_suffix(agent_name: str) -> str:
    return agent_name.lower().replace("agent", "").replace("worker", "").strip("_") or "worker"
