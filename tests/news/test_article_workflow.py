"""Article extraction, review, and briefing workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from margin.news.agentic_models import NewsArticleFinding
from margin.news.article_workflow import ArticleWorkflow
from margin.news.models import (
    NewsTarget,
    SourceLevel,
    TargetTriggerType,
    make_document_event,
)


class FakeLLMService:
    """Small fake structured LLM service keyed by prompt node name."""

    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        """Initialize the fake LLM service with queued structured responses.

        Args:
            responses: Mapping from prompt node name to a list of output dicts
                consumed in order by ``complete_structured``.
        """
        self.responses = {key: list(value) for key, value in responses.items()}

    def complete_structured(self, **kwargs: Any) -> SimpleNamespace:
        """Return the next configured response for the prompt node."""
        prompt = kwargs["prompt"]
        output = self.responses[prompt.node_name].pop(0)
        return SimpleNamespace(
            output=output,
            success=True,
            call_id="call_fake",
            model="fake",
            latency_ms=0.0,
            task_type=kwargs["task_type"],
            error_code=None,
        )


def test_article_workflow_returns_only_reviewed_finding() -> None:
    """Approved article drafts become event-bound findings."""
    workflow = ArticleWorkflow(
        llm_service=FakeLLMService(
            {
                "news_article_writer": [
                    {
                        "key_points": ["公告披露经营情况改善。"],
                        "materiality": "medium",
                        "sentiment": "positive",
                        "risk_flags": [],
                        "cited_spans": [{"start": 0, "end": 10}],
                        "confidence": 0.82,
                        "why_relevant_to_quant": "supports quality review",
                    }
                ],
                "news_writing_review": [
                    {"approved": True, "revision_notes": []},
                ],
            }
        ),
        max_review_rounds=2,
    )

    findings = workflow.extract_findings(
        run_id="nar_test",
        target=_target(),
        events=(_event(),),
    )

    assert len(findings) == 1
    assert findings[0].event_id == "evt_article"
    assert findings[0].security_id == "000001.SZ"
    assert findings[0].review_status == "approved"
    assert findings[0].key_points == ("公告披露经营情况改善。",)


def test_article_workflow_drops_repeatedly_rejected_finding() -> None:
    """Repeated writing-review rejection yields no approved finding."""
    workflow = ArticleWorkflow(
        llm_service=FakeLLMService(
            {
                "news_article_writer": [
                    {
                        "key_points": ["缺少引用的判断。"],
                        "cited_spans": [],
                        "confidence": 0.3,
                    },
                    {
                        "key_points": ["仍缺少引用。"],
                        "cited_spans": [],
                        "confidence": 0.3,
                    },
                ],
                "news_writing_review": [
                    {"approved": False, "revision_notes": ["missing citation"]},
                    {"approved": False, "revision_notes": ["still unsupported"]},
                ],
            }
        ),
        max_review_rounds=2,
    )

    findings = workflow.extract_findings(
        run_id="nar_test",
        target=_target(),
        events=(_event(),),
    )

    assert findings == ()


def test_article_workflow_repairs_invalid_local_citation_span() -> None:
    """LLM-approved drafts must still pass deterministic citation-span checks."""
    workflow = ArticleWorkflow(
        llm_service=FakeLLMService(
            {
                "news_article_writer": [
                    {
                        "key_points": ["公告披露经营情况改善。"],
                        "cited_spans": [{"start": 99, "end": 120}],
                        "confidence": 0.7,
                    },
                    {
                        "key_points": ["公告披露经营情况改善。"],
                        "cited_spans": [{"start": 0, "end": 10, "text": "公告披露经营情况改善"}],
                        "confidence": 0.82,
                    },
                ],
                "news_writing_review": [
                    {"approved": True, "revision_notes": []},
                    {"approved": True, "revision_notes": []},
                ],
            }
        ),
        max_review_rounds=2,
    )

    findings = workflow.extract_findings(
        run_id="nar_test",
        target=_target(),
        events=(_event(),),
    )

    assert len(findings) == 1
    assert findings[0].cited_spans == (
        {"start": 0, "end": 10, "text": "公告披露经营情况改善"},
    )


def test_article_workflow_builds_derived_brief_from_approved_findings() -> None:
    """Briefs are derived and retain finding/source references."""
    workflow = ArticleWorkflow(
        llm_service=FakeLLMService(
            {
                "news_summary_agent": [
                    {"summary": "平安银行出现一条经营改善相关公告。"},
                ],
            }
        ),
        max_review_rounds=2,
    )
    finding = NewsArticleFinding(
        finding_id="naf_test",
        run_id="nar_test",
        security_id="000001.SZ",
        event_id="evt_article",
        title="平安银行公告",
        source_url="https://example.com/article",
        key_points=("公告披露经营情况改善。",),
        cited_spans=({"start": 0, "end": 10},),
        review_status="approved",
        confidence=0.82,
        prompt_version="news-article-v0.3.0",
        prompt_hash="sha256:prompt",
        response_hash="sha256:response",
    )

    brief = workflow.build_brief(run_id="nar_test", target=_target(), findings=(finding,))

    assert brief is not None
    assert brief.is_derived is True
    assert brief.trust_level == "derived_low_trust"
    assert brief.finding_ids == ("naf_test",)
    assert brief.source_event_ids == ("evt_article",)
    assert brief.summary == "平安银行出现一条经营改善相关公告。"


def _target() -> NewsTarget:
    """Return one quant PASS target."""
    return NewsTarget(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        security_id="000001.SZ",
        symbol="000001.SZ",
        name="平安银行",
        trigger_type=TargetTriggerType.QUANT_PASS,
        decision_at=datetime(2026, 6, 29, tzinfo=UTC),
        priority=100,
    )


def _event():
    """Return one persisted-style document event."""
    return make_document_event(
        source_url="https://example.com/article",
        source_name="websearch",
        source_level=SourceLevel.L4,
        title="平安银行公告",
        content="公告披露经营情况改善，资产质量保持稳定。",
        symbols=["000001.SZ"],
        published_at=datetime(2026, 6, 29, tzinfo=UTC),
    ).model_copy(
        update={
            "event_id": "evt_article",
            "document_id": "doc_article",
            "snapshot_id": "snap_article",
        }
    )
