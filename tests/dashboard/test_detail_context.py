"""Tests for dashboard detail-context assembly."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.dashboard.detail_context import build_dashboard_detail_context


def test_detail_context_exposes_ai_empty_evidence_and_news_documents() -> None:
    """Context assembly should make empty AI evidence and news docs visible."""
    context = {
        "context_snapshot_id": "rcs_1",
        "decision_at": datetime(2026, 7, 2, 8, 5, tzinfo=UTC),
    }
    payload = {
        "analysis_summary": {
            "name": "爱施德",
            "reason_summary": "Quant screen pass.",
        },
        "news_context_bundle_id": "ncb_1",
        "evidence_package_id": "pkg_empty",
        "analysis_snapshot_id": "ans_1",
        "evidence_ids": [],
        "evidence_quality_status": "abstain_required",
        "news_target_complete": True,
        "quant_factor_details": {
            "ai_quant_profile": {
                "raw_factors": {
                    "pe_ttm": 34.2,
                    "dividend_yield": 0.048,
                    "return_20d": -0.07,
                }
            }
        },
    }
    review = {
        "review_id": "review_1",
        "graph_run_id": "graph_1",
        "outcome": "review_deferred",
        "conclusion": "",
        "confidence": 0.0,
        "evidence_ids": [],
        "assessment_freshness": "stale",
        "stale_reason": None,
    }
    documents = [
        {
            "event_id": "evt_match",
            "title": "投资者关系活动记录表",
            "source_level": 1,
            "source_url": "https://static.cninfo.com.cn/a.pdf",
            "snapshot_id": "snap_1",
            "published_at": datetime(2026, 7, 2, tzinfo=UTC),
            "symbols": [],
            "snippet": "证券代码：002416 证券简称：爱施德",
        },
        {
            "event_id": "evt_wrong",
            "title": "海目星年度报告",
            "source_level": 1,
            "source_url": "https://static.cninfo.com.cn/b.pdf",
            "snapshot_id": "snap_2",
            "published_at": datetime(2026, 7, 2, tzinfo=UTC),
            "symbols": [],
            "snippet": "公司代码：688559 公司简称：海目星",
        },
    ]
    trends = [
        {
            "metric": "adj_close",
            "label": "复权收盘价",
            "unit": "CNY",
            "points": [{"date": "2026-07-01", "value": 12.4}],
        }
    ]

    result = build_dashboard_detail_context(
        security_id="002416.SZ",
        context=context,
        payload=payload,
        review=review,
        assessment=None,
        documents=documents,
        trends=trends,
    )

    assert result["display_name"] == "爱施德"
    assert result["current_review"]["outcome"] == "review_deferred"
    assert result["current_review"]["reason"] == "证据包为空，AI 未形成可引用结论。"
    assert result["effective_assessment"]["freshness"] == "missing"
    assert result["factors"]["valuation"]["status"] == "missing_assessment"
    assert result["factors"]["raw_metrics"][0]["metric"] == "pe_ttm"
    assert result["factors"]["trends"] == trends
    assert result["evidence"][0]["linked_to_security"] is True
    assert result["evidence"][1]["linked_to_security"] is False


def test_detail_context_translates_deferred_ai_reason_into_thesis() -> None:
    """Deferred AI reviews should not masquerade as finished research theses."""
    context = {
        "context_snapshot_id": "rcs_2",
        "decision_at": datetime(2026, 7, 2, 8, 5, tzinfo=UTC),
    }
    payload = {
        "analysis_summary": {
            "name": "爱施德",
            "reason_summary": "Quant screen pass.",
        },
        "evidence_ids": [],
        "quant_factor_details": {},
    }
    review = {
        "review_id": "review_2",
        "graph_run_id": "graph_2",
        "outcome": "review_deferred",
        "conclusion": "",
        "confidence": 0.0,
        "evidence_ids": [],
        "assessment_freshness": "stale",
        "stale_reason": "news_target_incomplete",
    }

    result = build_dashboard_detail_context(
        security_id="002416.SZ",
        context=context,
        payload=payload,
        review=review,
        assessment=None,
        documents=[],
        trends=[],
    )

    assert result["current_review"]["reason"] == "News target 未完成，AI 复核延期。"
    assert result["thesis"]["statement"] == "News target 未完成，AI 复核延期。"
