"""v0.2 research service entrypoint tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.research.delta_repository import MemoryResearchDeltaRepository
from margin.research.graph.state import ReviewOutcome
from margin.research.service import (
    MemoryResearchContextRepository,
    ResearchContextSnapshot,
    ResearchService,
)

DECISION_AT = datetime(2026, 6, 23, tzinfo=UTC)


def test_v02_service_runs_by_context_snapshot_id() -> None:
    """v0.2 service runs the delta review graph from a frozen context ID."""
    context_repository = MemoryResearchContextRepository()
    context_repository.add(
        ResearchContextSnapshot(
            context_snapshot_id="ctx-service-v02",
            security_id="000001.SZ",
            scope_version_id="scope-1",
            decision_at=DECISION_AT,
            payload_hash="sha256:ctx-service-v02",
            payload={
                "quant_input_valid": True,
                "pit_valid": True,
                "news_target_complete": True,
                "provider_budget_available": True,
                "review_due": False,
                "material_quant_change": False,
                "material_valuation_change": False,
                "material_news_change": False,
                "assumption_change": False,
                "ambiguous_change": False,
                "previous_effective_assessment_id": "assess-old",
            },
        )
    )
    service = ResearchService(context_repository=context_repository)

    result = service.run_delta_review(context_snapshot_id="ctx-service-v02")

    assert result.graph_run_id.startswith("graph_")
    assert result.context_snapshot_id == "ctx-service-v02"
    assert result.current_review_outcome == ReviewOutcome.CARRY_FORWARD_VERIFIED
    assert result.effective_assessment_id == "assess-old"
    assert result.llm_call_count == 0


def test_v02_service_replays_terminal_review_without_running_graph_again() -> None:
    """A repeated context request returns the immutable terminal review."""
    context_repository = MemoryResearchContextRepository()
    delta_repository = MemoryResearchDeltaRepository()
    context_repository.add(
        ResearchContextSnapshot(
            context_snapshot_id="ctx-service-replay",
            security_id="000001.SZ",
            scope_version_id="scope-1",
            decision_at=DECISION_AT,
            payload_hash="sha256:ctx-service-replay",
            payload={
                "quant_input_valid": True,
                "pit_valid": True,
                "news_target_complete": True,
                "provider_budget_available": True,
                "review_due": False,
                "material_quant_change": False,
                "material_valuation_change": False,
                "material_news_change": False,
                "assumption_change": False,
                "ambiguous_change": False,
                "previous_effective_assessment_id": "assess-old",
            },
        )
    )
    service = ResearchService(
        context_repository=context_repository,
        delta_repository=delta_repository,
    )

    first = service.run_delta_review("ctx-service-replay")
    second = service.run_delta_review("ctx-service-replay")

    assert second == first
    assert delta_repository.get_review_by_graph_run(first.graph_run_id) is not None
