"""Focused LangGraph orchestration tests for GeneralQnaWorkerExecutor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agents.context.repository import MemoryContextRepository
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextFact,
    ContextPack,
    WorkerTaskRequest,
)
from margin.agents.runtime.execution_context import WorkerExecutionContext
from margin.agents.runtime.worker_executors import (
    GeneralQnaWorkerExecutor,
    GeneralQnaWorkflowState,
)
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.gateway import ToolGateway
from margin.agents.tools.specs import ToolCallRequest, ToolSpec
from margin.research.llm import LLMResult


class _RecordingAnswerLLM:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.prompts: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        del response_schema
        assert temperature == 0.0
        self.events.append("llm")
        self.prompts.append(prompt)
        return LLMResult(
            output={"content": "当前研究候选包含 000001.SZ。"},
            raw_response="当前研究候选包含 000001.SZ。",
            model="test",
            success=True,
            latency_ms=0.0,
        )


class _ObservedGeneralQnaExecutor(GeneralQnaWorkerExecutor):
    def __init__(self, **kwargs: Any) -> None:
        self.node_inputs: list[tuple[str, frozenset[str], tuple[str, ...]]] = []
        super().__init__(**kwargs)

    def _load_candidates_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        self._record("load_candidates", state)
        return super()._load_candidates_node(state)

    def _generate_answer_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        self._record("generate_answer", state)
        return super()._generate_answer_node(state)

    def _finalize_node(
        self,
        state: GeneralQnaWorkflowState,
    ) -> dict[str, Any]:
        self._record("finalize", state)
        return super()._finalize_node(state)

    def _record(self, node: str, state: GeneralQnaWorkflowState) -> None:
        self.node_inputs.append(
            (node, frozenset(state), tuple(state.get("node_trace", ())))
        )


def test_general_qna_execute_uses_langgraph_state_flow_and_gateway_only() -> None:
    events: list[str] = []
    tool_requests: list[ToolCallRequest] = []
    catalog = ToolCatalog()

    def dashboard_handler(request: ToolCallRequest) -> dict[str, Any]:
        events.append("gateway")
        tool_requests.append(request)
        return {
            "scope_version_id": "scope-1",
            "universe": "ALL_A",
            "status": "ready",
            "as_of": "2026-07-10T00:00:00+00:00",
            "row_count": 1,
            "rows": [
                {
                    "security_id": "security-1",
                    "symbol": "000001.SZ",
                    "final_score": 91.5,
                    "confidence": 0.9,
                    "screening_status": "candidate",
                }
            ],
            "safe_summary": "Dashboard candidate source has 1 row.",
        }

    catalog.register(_dashboard_tool_spec(), dashboard_handler)
    audit_store = InMemoryToolAuditStore()
    gateway = ToolGateway(catalog=catalog, audit_store=audit_store)
    llm = _RecordingAnswerLLM(events)
    executor = _ObservedGeneralQnaExecutor(
        llm_provider_factory=lambda: llm,
    )
    request = _request()
    graph = executor._graph.get_graph()  # noqa: SLF001

    assert set(graph.nodes) == {
        "__start__",
        "load_candidates",
        "generate_answer",
        "finalize",
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "load_candidates"),
        ("load_candidates", "generate_answer"),
        ("generate_answer", "finalize"),
        ("finalize", "__end__"),
    }

    bundle = executor.execute(request, _context(gateway))

    assert bundle.result.status is AgentExecutionStatus.SUCCEEDED
    assert bundle.answer == "当前研究候选包含 000001.SZ。"
    assert bundle.table_rows == [
        {
            "security_id": "security-1",
            "symbol": "000001.SZ",
            "final_score": 91.5,
            "confidence": 0.9,
            "screening_status": "candidate",
        }
    ]
    assert [artifact.artifact_type for artifact in bundle.artifacts] == [
        "analysis_table",
        "qna_answer",
    ]
    assert events == ["gateway", "llm"]
    assert len(llm.prompts) == 1
    assert "000001.SZ" in llm.prompts[0]
    assert len(tool_requests) == 1
    assert tool_requests[0].task_id == request.worker_task_id
    assert tool_requests[0].caller_agent == request.worker_agent
    assert tool_requests[0].idempotency_key == (
        f"{request.idempotency_key}:dashboard.read_candidates"
    )
    assert [record.tool_name for record in audit_store.records.values()] == [
        "dashboard.read_candidates"
    ]
    assert bundle.result.audit_event_refs == tuple(audit_store.records)
    assert executor.node_inputs == [
        (
            "load_candidates",
            frozenset({"request", "context", "node_trace"}),
            (),
        ),
        (
            "generate_answer",
            frozenset(
                {
                    "request",
                    "context",
                    "node_trace",
                        "table_artifact",
                        "table_rows",
                        "audit_event_refs",
                }
            ),
            ("load_candidates",),
        ),
        (
            "finalize",
            frozenset(
                {
                    "request",
                    "context",
                    "node_trace",
                        "table_artifact",
                        "table_rows",
                        "audit_event_refs",
                        "answer",
                }
            ),
            ("load_candidates", "generate_answer"),
        ),
    ]


def _dashboard_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="dashboard.read_candidates",
        tool_version="v1",
        description="Read approved dashboard candidates.",
        owner_domain="general",
        input_schema_ref="dashboard.read_candidates.input",
        output_schema_ref="dashboard.read_candidates.output",
        required_data_access=(DataAccessPolicy.READ_DASHBOARD,),
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=30_000,
        max_output_bytes=64_000,
        allowed_runtimes=("langgraph",),
    )


def _request() -> WorkerTaskRequest:
    return WorkerTaskRequest(
        run_id="run-general",
        domain_task_id="dt-general",
        worker_task_id="wt-general",
        parent_agent="GeneralQnaExpertAgent",
        worker_agent="GeneralQnaWorker",
        skill_id="answer_general_qna",
        task_goal="Answer from approved dashboard candidates.",
        input_context_pack_ref="ctx-general",
        required_output_types=("analysis_table", "qna_answer"),
        tool_policy_ref="policy-general",
        capability_token_ref="cap-general",
        token_budget=2_000,
        max_tool_calls=1,
        deadline_ms=30_000,
        idempotency_key="idem-general",
    )


def _context(gateway: ToolGateway) -> WorkerExecutionContext:
    context_pack = ContextPack(
        context_pack_id="ctx-general",
        run_id="run-general",
        requester_agent="GeneralQnaExpertAgent",
        target_agent="GeneralQnaWorker",
        purpose="worker_execution",
        token_budget=2_000,
        facts=(
            ContextFact(
                fact_id="fact-status",
                statement="Dashboard is ready.",
                confidence=1.0,
                fact_type="data_status",
            ),
        ),
        compression_policy_version="test-v1",
    )
    token = CapabilityToken(
        token_id="cap-general",
        run_id="run-general",
        issued_by="GeneralQnaExpertAgent",
        issued_to="GeneralQnaWorker",
        domain="general",
        data_access=(DataAccessPolicy.READ_DASHBOARD,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("analysis_table", "qna_answer"),
        allowed_tool_names=("dashboard.read_candidates",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=1,
        max_result_bytes=64_000,
        bound_task_id="wt-general",
        bound_context_pack_id="ctx-general",
    )
    return WorkerExecutionContext(
        command=SimpleNamespace(
            run_id="run-general",
            scope_version_id="scope-1",
            universe="ALL_A",
            language="zh",
            message="今日研究候选有哪些？",
        ),
        context_pack=context_pack,
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        tool_gateway=gateway,
        capability_token=token,
        llm_provider_factory=lambda: _RecordingAnswerLLM([]),
    )
