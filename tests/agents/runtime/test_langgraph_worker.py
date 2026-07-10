"""Unit tests for the generic dynamic LangGraph WorkerAgent runtime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from margin.agent_runtime.context_store import MemoryAgentContextStore, make_context_artifact
from margin.agents.protocol.models import AgentExecutionStatus, ContextPack, WorkerTaskRequest
from margin.agents.runtime.langgraph_worker import LangGraphWorkerExecutor
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.gateway import InMemoryToolRateLimiter, ToolGateway
from margin.agents.tools.specs import ToolSpec
from margin.research.llm import LLMResult


class _SequenceLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        del response_schema, temperature
        self.prompts.append(prompt)
        return LLMResult(
            output=self.responses.pop(0),
            model="test",
            success=True,
            latency_ms=0.0,
        )


class _AdvancingClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_langgraph_worker_observes_multiple_tools_then_finishes() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    llm = _SequenceLLM(
        [
            {"action": "tool", "tool_name": "context.echo", "tool_input": {"value": 2}},
            {"action": "tool", "tool_name": "context.echo", "tool_input": {"value": 3}},
            {
                "action": "finish",
                "answer": "The combined value is 5.",
                "artifacts": [
                    {
                        "artifact_type": "analysis_table",
                        "payload_json": {"columns": ["value"], "rows": [{"value": 5}]},
                    }
                ],
            },
        ]
    )
    request = _request(
        required_output_types=("analysis_table", "qna_answer", "worker_activity"),
        max_tool_calls=3,
    )

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=gateway,
        llm_provider=llm,  # type: ignore[arg-type]
    ).execute(request, capability_token=_token(max_tool_calls=3))

    assert bundle.result.status is AgentExecutionStatus.SUCCEEDED
    assert calls == [{"value": 2}, {"value": 3}]
    assert len(llm.prompts) == 3
    assert {artifact.artifact_type for artifact in bundle.artifacts} == {
        "analysis_table",
        "qna_answer",
        "worker_activity",
    }
    activity = next(
        artifact for artifact in bundle.artifacts if artifact.artifact_type == "worker_activity"
    )
    assert activity.payload_json["tool_call_count"] == 2
    assert [item["output"] for item in activity.payload_json["observations"]] == [
        {"value": 2},
        {"value": 3},
    ]
    assert bundle.table_rows == [{"value": 5}]


def test_langgraph_worker_replans_after_invisible_tool_rejection() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    llm = _SequenceLLM(
        [
            {"action": "tool", "tool_name": "workspace.hidden", "tool_input": {}},
            {
                "action": "block",
                "reason": "The requested tool is not authorized for this worker.",
            },
        ]
    )
    request = _request(max_tool_calls=2)

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore()),
        llm_provider=llm,  # type: ignore[arg-type]
    ).execute(request, capability_token=_token(max_tool_calls=2))

    assert bundle.result.status is AgentExecutionStatus.BLOCKED
    assert bundle.result.error_code == "planner_blocked"
    assert calls == []
    activity = next(
        artifact for artifact in bundle.artifacts if artifact.artifact_type == "worker_activity"
    )
    assert activity.payload_json["observations"][0]["error_code"] == "tool_not_visible"
    assert len(llm.prompts) == 2


def test_minimum_tool_calls_counts_only_successful_gateway_results() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    llm = _SequenceLLM(
        [
            {"action": "tool", "tool_name": "workspace.hidden", "tool_input": {}},
            {"action": "finish", "answer": "done"},
        ]
    )

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore()),
        llm_provider=llm,  # type: ignore[arg-type]
        minimum_tool_calls=1,
    ).execute(_request(max_tool_calls=2), capability_token=_token(max_tool_calls=2))

    assert bundle.result.status is AgentExecutionStatus.BLOCKED
    assert bundle.result.error_code == "minimum_tool_calls_not_met"
    assert calls == []


def test_langgraph_worker_observes_tool_gateway_rejection_before_blocking() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    llm = _SequenceLLM(
        [
            {"action": "tool", "tool_name": "context.echo", "tool_input": {"value": 1}},
            {"action": "block", "reason": "The authorized tool is rate limited."},
        ]
    )
    request = _request(max_tool_calls=2)

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(
            catalog=catalog,
            audit_store=InMemoryToolAuditStore(),
            rate_limiter=InMemoryToolRateLimiter(limit_per_tool=0),
        ),
        llm_provider=llm,  # type: ignore[arg-type]
    ).execute(request, capability_token=_token(max_tool_calls=2))

    assert bundle.result.status is AgentExecutionStatus.BLOCKED
    assert calls == []
    activity = next(
        artifact for artifact in bundle.artifacts if artifact.artifact_type == "worker_activity"
    )
    observation = activity.payload_json["observations"][0]
    assert observation["error_code"] == "rate_limited"
    assert observation["audit_ref"]
    assert len(llm.prompts) == 2


def test_langgraph_worker_blocks_before_exceeding_max_tool_calls() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    llm = _SequenceLLM(
        [
            {"action": "tool", "tool_name": "context.echo", "tool_input": {"value": 1}},
            {"action": "tool", "tool_name": "context.echo", "tool_input": {"value": 2}},
        ]
    )
    request = _request(max_tool_calls=1)

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore()),
        llm_provider=llm,  # type: ignore[arg-type]
    ).execute(request, capability_token=_token(max_tool_calls=1))

    assert bundle.result.status is AgentExecutionStatus.BLOCKED
    assert bundle.result.error_code == "max_tool_calls_exceeded"
    assert calls == [{"value": 1}]
    assert len(llm.prompts) == 2


def test_langgraph_worker_accepts_injected_checkpointer() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    checkpointer = InMemorySaver()
    request = _request(max_tool_calls=0)
    worker = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore()),
        llm_provider=_SequenceLLM([{"action": "finish", "answer": "done"}]),  # type: ignore[arg-type]
        checkpointer=checkpointer,
    )

    bundle = worker.execute(request, capability_token=_token(max_tool_calls=0))

    assert bundle.result.status is AgentExecutionStatus.SUCCEEDED
    checkpoints = tuple(
        checkpointer.list(
            {
                "configurable": {
                    "thread_id": f"{request.run_id}:{request.worker_task_id}",
                }
            }
        )
    )
    assert checkpoints


def test_langgraph_worker_blocks_when_deadline_is_already_exhausted() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    llm = _SequenceLLM([{"action": "finish", "answer": "too late"}])
    request = _request(max_tool_calls=1, deadline_ms=1)

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore()),
        llm_provider=llm,  # type: ignore[arg-type]
        monotonic=_AdvancingClock([0.0, 1.0]),
    ).execute(request, capability_token=_token(max_tool_calls=1))

    assert bundle.result.status is AgentExecutionStatus.BLOCKED
    assert bundle.result.error_code == "deadline_exceeded"
    assert llm.prompts == []
    assert calls == []


def test_langgraph_worker_receives_verified_upstream_artifact_payloads() -> None:
    calls: list[dict[str, Any]] = []
    catalog = _catalog(calls)
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    llm = _SequenceLLM([{"action": "finish", "answer": "used upstream"}])
    request = _request(max_tool_calls=0).model_copy(
        update={"input_artifact_refs": ("artifact-upstream",)}
    )
    store = MemoryAgentContextStore()
    store.add_artifact(
        make_context_artifact(
            artifact_id="artifact-upstream",
            run_id=request.run_id,
            artifact_type="analysis_table",
            producer_agent="UpstreamWorker",
            payload_json={"decision": "use-upstream-value", "value": 42},
            source_refs=("tool_audit_upstream",),
        )
    )
    context_pack = ContextPack(
        context_pack_id=request.input_context_pack_ref,
        run_id=request.run_id,
        requester_agent="GeneralExpertAgent",
        target_agent=request.worker_agent,
        purpose="worker_execution",
        token_budget=2_000,
        facts=(),
        compression_policy_version="test-v1",
    )

    bundle = LangGraphWorkerExecutor(
        tool_catalog=catalog,
        tool_gateway=gateway,
        llm_provider=llm,  # type: ignore[arg-type]
    ).execute(
        request,
        SimpleNamespace(context_pack=context_pack, context_store=store),  # type: ignore[arg-type]
        capability_token=_token(max_tool_calls=0),
    )

    assert bundle.result.status is AgentExecutionStatus.SUCCEEDED
    assert "artifact-upstream" in llm.prompts[0]
    assert "use-upstream-value" in llm.prompts[0]


def _catalog(calls: list[dict[str, Any]]) -> ToolCatalog:
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            tool_name="context.echo",
            tool_version="v1",
            description="Echo a structured value.",
            owner_domain="general",
            input_schema_ref="context.echo.input",
            output_schema_ref="context.echo.output",
            required_data_access=(DataAccessPolicy.NO_DATA,),
            required_write_policy=(),
            required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
            idempotent=False,
            mutates_state=False,
            timeout_ms=1000,
            max_output_bytes=4096,
            allowed_runtimes=("langgraph",),
        ),
        lambda request: calls.append(dict(request.input_json)) or dict(request.input_json),
    )
    return catalog


def _token(*, max_tool_calls: int) -> CapabilityToken:
    return CapabilityToken(
        token_id="cap_worker",
        run_id="run_worker",
        issued_by="ExpertAgent",
        issued_to="GenericWorker",
        domain="general",
        data_access=(DataAccessPolicy.NO_DATA,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("analysis_table", "qna_answer", "worker_activity"),
        allowed_tool_names=("context.echo",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=max_tool_calls,
        max_result_bytes=16_000,
    )


def _request(
    *,
    required_output_types: tuple[str, ...] = ("worker_activity",),
    max_tool_calls: int,
    deadline_ms: int = 5000,
) -> WorkerTaskRequest:
    return WorkerTaskRequest(
        run_id="run_worker",
        domain_task_id="dt_general",
        worker_task_id="wt_generic",
        parent_agent="GeneralExpertAgent",
        worker_agent="GenericWorker",
        skill_id="execute_goal",
        task_goal="Use authorized tools to complete the goal.",
        input_context_pack_ref="ctx_worker",
        required_output_types=required_output_types,
        tool_policy_ref="cap_worker",
        capability_token_ref="cap_worker",
        token_budget=2000,
        max_tool_calls=max_tool_calls,
        deadline_ms=deadline_ms,
        idempotency_key="idem_worker",
    )
