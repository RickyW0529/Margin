"""Tests for data readiness artifacts in Agent ContextPacks."""

from __future__ import annotations

from types import SimpleNamespace

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agents.context.readiness import ReadinessStatus
from margin.agents.context.readiness_builder import DataReadinessBuilder
from margin.agents.context.repository import MemoryContextRepository
from margin.agents.runtime.service import AgentRuntimeService, UserQnaCommand
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import DeterministicLLMProvider


def test_data_readiness_builder_distinguishes_dashboard_empty() -> None:
    """Empty dashboard candidates should be readiness=empty, not error."""
    artifact = DataReadinessBuilder(
        dashboard_services=DashboardServiceBundle.in_memory(),
        warehouse_repository=None,
    ).build_for_user_qna(_command())

    sources = {source["source_name"]: source for source in artifact.payload_json["sources"]}

    assert sources["dashboard_candidates"]["status"] == ReadinessStatus.EMPTY
    assert sources["dashboard_candidates"]["row_count"] == 0
    assert sources["warehouse"]["status"] == ReadinessStatus.NOT_CONFIGURED


def test_data_readiness_builder_records_dashboard_exception_as_error() -> None:
    """Dashboard exceptions should preserve a safe error code."""
    artifact = DataReadinessBuilder(
        dashboard_services=_exploding_dashboard_services(),
        warehouse_repository=None,
    ).build_for_user_qna(_command())

    sources = {source["source_name"]: source for source in artifact.payload_json["sources"]}

    assert sources["dashboard_candidates"]["status"] == ReadinessStatus.ERROR
    assert sources["dashboard_candidates"]["error_code"] == "RuntimeError"
    assert sources["dashboard_candidates"]["retryable"] is True


def test_context_pack_includes_data_readiness_artifact_ref_and_facts() -> None:
    """User Q&A ContextPack should include data_readiness refs and facts."""
    context_store = MemoryAgentContextStore()
    context_repository = MemoryContextRepository()
    service = AgentRuntimeService(
        context_store=context_store,
        context_repository=context_repository,
        dashboard_services=DashboardServiceBundle.in_memory(),
        llm_provider_factory=lambda: DeterministicLLMProvider(response={}),
    )

    pack = service._build_and_store_context_pack(_command())  # noqa: SLF001

    readiness_ref = "ctx_run_readiness_data_readiness"
    readiness_artifact = context_store.get_artifact(readiness_ref)
    facts = context_repository.list_context_facts(pack.context_pack_id)

    assert readiness_ref in pack.included_artifact_refs
    assert readiness_artifact is not None
    assert any(
        fact.fact_type == "data_status" and fact.subject_id == "dashboard_candidates"
        for fact in facts
    )


def _command() -> UserQnaCommand:
    return UserQnaCommand(
        run_id="run_readiness",
        scope_version_id="scope-1",
        message="现在能做什么",
        universe="ALL_A",
        language="zh",
        conversation_context=(),
    )


def _exploding_dashboard_services() -> object:
    return SimpleNamespace(
        query=_ExplodingDashboardQuery(),
        providers=SimpleNamespace(list_status=lambda: []),
    )


class _ExplodingDashboardQuery:
    def list_research_candidates_v2(self, **_kwargs: object) -> object:
        raise RuntimeError("dashboard down")
