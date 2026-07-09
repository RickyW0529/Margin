"""Contracts for the v1 application-facing Agent runtime service."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agents.context.repository import MemoryContextRepository
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import DeterministicLLMProvider, LLMResult

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_v1_user_qna_service_creates_plan_and_final_answer_artifact() -> None:
    """User Q&A should run through v1 plan/capsule/final-answer objects."""
    from margin.agents.runtime.service import AgentRuntimeService, UserQnaCommand

    context_store = MemoryAgentContextStore()
    context_repository = MemoryContextRepository()
    dashboard_services = _dashboard_services()
    llm_provider = _AnswerOnlyLLMProvider("当前研究候选包含 000001.SZ。")
    service = AgentRuntimeService(
        context_store=context_store,
        context_repository=context_repository,
        dashboard_services=dashboard_services,
        llm_provider_factory=lambda: llm_provider,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_v1",
            scope_version_id="scope-1",
            message="今日研究候选有哪些？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert result.guardrail.allowed is True
    assert result.global_plan.created_by == "MainAgent"
    assert result.global_plan.run_type == "user_qna"
    assert result.global_plan.domain_tasks
    assert all(task.from_agent == "MainAgent" for task in result.global_plan.domain_tasks)
    assert all(step.expert_agent_name.endswith("ExpertAgent") for step in result.trace_steps)
    assert result.final_answer.answer_text == "当前研究候选包含 000001.SZ。"
    assert result.final_answer.final_audit_report_ref == "fa_ar_qna_v1"
    assert context_repository.get_context_pack("ctxpack_ar_qna_v1_mainagent") is not None
    assert context_repository.get_domain_capsule("dcc_ar_qna_v1_general") is not None
    assert {
        (edge.from_ref, edge.to_ref, edge.edge_type)
        for edge in context_repository.list_lineage_edges("ar_qna_v1")
    } >= {
        ("ctxpack_ar_qna_v1_mainagent", "chat_summary:e3b0c44298fc1c14", "source_ref"),
        ("dcc_ar_qna_v1_general", "ctxpack_ar_qna_v1_mainagent", "source_ref"),
    }
    artifact_ids = {artifact.artifact_id for artifact in result.artifacts}
    assert result.final_answer.artifact_id in artifact_ids
    assert context_store.get_artifact(result.final_answer.artifact_id) is not None
    assert any(artifact.artifact_type == "analysis_table" for artifact in result.artifacts)
    assert llm_provider.calls == ["answer"]


def test_api_route_no_longer_imports_legacy_main_agent_execution() -> None:
    """The HTTP route should depend on the v1 runtime service, not v0 executors."""
    import margin.api.routes.agent_runtime as route_module

    source = inspect.getsource(route_module)

    assert "get_agent_runtime_service" in source
    assert "MainAgentRuntime" not in source
    assert "DataAnalystAgent" not in source
    assert "GeneralQnaAgent" not in source
    assert "_execute_user_qna_plan" not in source


def _dashboard_services() -> DashboardServiceBundle:
    """Return an in-memory dashboard bundle with one candidate."""
    repository = MemoryDashboardRepository()
    run = ResearchRun(
        run_id="run-1",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ"],
        status="partial",
        item_count=1,
        published_count=1,
    )
    item = ResearchItem(
        item_id="item-1",
        run_id=run.run_id,
        symbol="000001.SZ",
        signal_type="research_candidate",
        confidence=0.82,
        statement="经营现金流改善",
        workflow_run_id="wf-1",
        snapshot_id="assess-old",
        status="published",
    )
    repository.add_run(run)
    repository.add_items([item])
    return DashboardServiceBundle.in_memory(dashboard_repository=repository)


class _AnswerOnlyLLMProvider(DeterministicLLMProvider):
    """Test LLM that records user-answer calls."""

    def __init__(self, answer: str) -> None:
        """Initialize the deterministic answer provider."""
        super().__init__(response={})
        self._answer = answer
        self.calls: list[str] = []

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Return a deterministic answer and reject planner-style calls."""
        del prompt, temperature
        if response_schema is not None:
            raise AssertionError("v1 user Q&A service must not use the v0 planner prompt")
        self.calls.append("answer")
        return LLMResult(
            output={"content": self._answer},
            model="test",
            success=True,
            latency_ms=0.0,
            raw_response=self._answer,
        )
