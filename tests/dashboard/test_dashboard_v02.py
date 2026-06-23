"""v0.2 dashboard BFF DTO and pagination tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.dashboard.models import (
    DashboardFilters,
    DashboardPageInfo,
    DashboardSort,
    ResearchCandidateListItemV2,
    ResearchCandidateListResponse,
    ResearchItem,
    ResearchRun,
)
from margin.dashboard.repository import MemoryDashboardRepository

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_candidate_list_response_separates_current_and_effective() -> None:
    """candidate list response separates current and effective assessment."""
    item = ResearchCandidateListItemV2(
        item_id="item-1",
        security_id="000001.SZ",
        symbol="000001",
        name="平安银行",
        scope_version_id="scope-1",
        screening_status="pass",
        data_status="complete",
        risk_flags=(),
        review_required=False,
        research_guardrail="allow_research",
        current_review_outcome="review_deferred",
        effective_assessment_id="assess-old",
        assessment_freshness="stale",
        stale_reason="news_target_incomplete",
        final_score=82.3,
        discount_rate=0.28,
        confidence=0.64,
        last_checked_at=DECISION_AT,
    )
    response = ResearchCandidateListResponse(
        items=(item,),
        page_info=DashboardPageInfo(
            next_cursor="cursor-2",
            has_next_page=True,
            page_size=50,
        ),
        facets={"screening_status": {"pass": 1}},
        as_of=DECISION_AT,
        scope_version_id="scope-1",
    )

    assert response.items[0].current_review_outcome == "review_deferred"
    assert response.items[0].effective_assessment_id == "assess-old"
    assert response.page_info.has_next_page is True


def test_memory_repository_paginates_candidates_with_opaque_cursor() -> None:
    """memory repository returns one server page and an opaque safe cursor."""
    repository = MemoryDashboardRepository()
    run = ResearchRun(
        run_id="run-v02",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ", "000002.SZ"],
        item_count=2,
        published_count=2,
    )
    repository.add_run(run)
    repository.add_items(
        [
            ResearchItem(
                item_id="item-high",
                run_id=run.run_id,
                symbol="000001.SZ",
                signal_type="research_candidate",
                confidence=0.91,
                status="published",
            ),
            ResearchItem(
                item_id="item-low",
                run_id=run.run_id,
                symbol="000002.SZ",
                signal_type="watch",
                confidence=0.70,
                status="published",
            ),
        ]
    )

    first_page = repository.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(screening_status="pass"),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=None,
        limit=1,
    )
    second_page = repository.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(screening_status="pass"),
        sort=DashboardSort(field="final_score", direction="desc"),
        cursor=first_page.page_info.next_cursor,
        limit=1,
    )

    assert [item.item_id for item in first_page.items] == ["item-high"]
    assert [item.item_id for item in second_page.items] == ["item-low"]
    assert first_page.page_info.next_cursor is not None
    assert "select" not in first_page.page_info.next_cursor.lower()
    assert "secret" not in first_page.page_info.next_cursor.lower()
