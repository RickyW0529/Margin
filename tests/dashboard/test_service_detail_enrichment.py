"""Dashboard query-service enrichment tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.dashboard.models import DashboardFilters, DashboardSort, ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardQueryService

DECISION_AT = datetime(2026, 7, 2, 8, 5, tzinfo=UTC)


def _repository() -> MemoryDashboardRepository:
    """Build a repository with one quant-projected dashboard item.

    Returns:
        MemoryDashboardRepository: .
    """
    repo = MemoryDashboardRepository()
    run = ResearchRun(
        run_id="dr_detail",
        decision_at=DECISION_AT,
        strategy_id="qr_detail",
        version_id="scope-default-v0.3.0",
        universe=["002416.SZ"],
        item_count=1,
        published_count=1,
    )
    repo.add_run(run)
    repo.add_items(
        [
            ResearchItem(
                item_id="di_detail",
                run_id=run.run_id,
                symbol="002416.SZ",
                signal_type="quant_screen:pass",
                confidence=0.925,
                statement="Quant screen pass.",
                workflow_run_id="qr_detail",
                snapshot_id="qres_detail",
                status="published",
            )
        ]
    )
    return repo


def test_candidate_list_uses_profile_display_name() -> None:
    """Candidate rows should display the Chinese security name when available.

    Returns:
        None: .
    """
    service = DashboardQueryService(
        _repository(),
        quant_profile_loader=lambda _: {"display_name": "爱施德"},
    )

    page = service.list_research_candidates_v2(
        scope_version_id="scope-default-v0.3.0",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(),
        cursor=None,
        limit=20,
    )

    assert page.items[0].name == "爱施德"


def test_item_detail_merges_context_review_news_valuation_and_trends() -> None:
    """Detail DTO should expose AI status, news documents, valuation state, and trends.

    Returns:
        None: .
    """
    service = DashboardQueryService(
        _repository(),
        quant_profile_loader=lambda _: {
            "display_name": "爱施德",
            "factor_scores": [{"factor_key": "quality_score", "label": "质量", "score": 100.0}],
        },
        detail_context_loader=lambda *_: {
            "current_review": {
                "outcome": "review_deferred",
                "reason": "证据包为空，AI 未形成可引用结论。",
                "conclusion": "证据不足，等待补证。",
                "confidence": 0.0,
            },
            "effective_assessment": {
                "assessment_id": None,
                "freshness": "stale",
                "stale_reason": "empty_evidence_package",
            },
            "thesis": {
                "statement": "证据不足，等待补证。",
                "ai_status": "review_deferred",
            },
            "evidence": [
                {
                    "evidence_id": "evt_1",
                    "title": "投资者关系活动记录表",
                    "source_level": "L1",
                    "locator": "news_document",
                    "source_url": "https://static.cninfo.com.cn/finalpage/demo.pdf",
                    "snippet": "证券代码：002416 证券简称：爱施德",
                    "linked_to_security": False,
                }
            ],
            "factors": {
                "valuation": {
                    "discount_rate": None,
                    "status": "missing_assessment",
                    "message": "AI 估值未形成。",
                },
                "trends": [
                    {
                        "metric": "close",
                        "label": "收盘价",
                        "unit": "CNY",
                        "points": [
                            {"date": "2026-06-01", "value": 10.2},
                            {"date": "2026-07-01", "value": 12.4},
                        ],
                    }
                ],
            },
            "versions": {"context_snapshot_id": "rcs_detail"},
        },
    )

    detail = service.get_item_detail_v2("di_detail")

    assert detail.item.name == "爱施德"
    assert detail.current_review["outcome"] == "review_deferred"
    assert detail.thesis["ai_status"] == "review_deferred"
    assert detail.evidence[0]["title"] == "投资者关系活动记录表"
    assert detail.evidence[0]["linked_to_security"] is False
    assert detail.factors["valuation"]["status"] == "missing_assessment"
    assert detail.factors["trends"][0]["points"][1]["value"] == 12.4
    assert detail.versions["context_snapshot_id"] == "rcs_detail"
