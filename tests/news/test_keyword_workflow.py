"""Keyword writer/reviewer workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from margin.news.keyword_workflow import KeywordWorkflow
from margin.news.models import NewsTarget, TargetTriggerType
from margin.news.query_templates import QueryTemplateFactory


class FakeLLMService:
    """Small fake structured LLM service keyed by prompt node name."""

    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        """Initialize the fake LLM service with queued structured responses.

        Args:
            responses: Mapping from prompt node name to a list of output dicts
                consumed in order by ``complete_structured``.
        """
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[str] = []

    def complete_structured(self, **kwargs: Any) -> SimpleNamespace:
        """Return the next configured response for the prompt node."""
        prompt = kwargs["prompt"]
        self.calls.append(prompt.node_name)
        output = self.responses[prompt.node_name].pop(0)
        return SimpleNamespace(
            output=output,
            success=True,
            call_id=f"call_{len(self.calls)}",
            model="fake",
            latency_ms=0.0,
            task_type=kwargs["task_type"],
            error_code=None,
        )


def test_keyword_workflow_returns_approved_plan() -> None:
    """Approved keyword drafts become a non-fallback search plan."""
    workflow = KeywordWorkflow(
        llm_service=FakeLLMService(
            {
                "news_keyword_writer": [
                    {"queries": ["site:cninfo.com.cn 平安银行 000001 公告 业绩"]},
                ],
                "news_keyword_review": [
                    {"approved": True, "revision_notes": []},
                ],
            }
        ),
        query_factory=QueryTemplateFactory(),
        max_review_rounds=2,
    )

    plan = workflow.build_plan(run_id="nar_test", target=_target())

    assert plan.review_status == "approved"
    assert plan.fallback_used is False
    assert plan.queries == ("site:cninfo.com.cn 平安银行 000001 公告 业绩",)


def test_keyword_workflow_falls_back_after_repeated_review_rejection() -> None:
    """Repeated review rejection falls back to deterministic templates."""
    target = _target()
    query_factory = QueryTemplateFactory()
    workflow = KeywordWorkflow(
        llm_service=FakeLLMService(
            {
                "news_keyword_writer": [
                    {"queries": ["平安银行"]},
                    {"queries": ["平安银行"]},
                ],
                "news_keyword_review": [
                    {"approved": False, "revision_notes": ["missing ticker"]},
                    {"approved": False, "revision_notes": ["still too broad"]},
                ],
            }
        ),
        query_factory=query_factory,
        max_review_rounds=2,
    )

    plan = workflow.build_plan(run_id="nar_test", target=target)

    assert plan.review_status == "fallback"
    assert plan.fallback_used is True
    assert plan.queries == tuple(query.query for query in query_factory.build_queries(target))


def test_keyword_workflow_local_guardrail_rejects_wrong_company_and_market_terms() -> None:
    """Local guardrails override an overly permissive LLM reviewer."""
    target = _target(
        security_id="002357.SZ",
        name="富临运业",
        aliases=("富临运业集团",),
        industry_terms=("道路运输",),
    )
    workflow = KeywordWorkflow(
        llm_service=FakeLLMService(
            {
                "news_keyword_writer": [
                    {
                        "queries": [
                            "赣锋锂业 002357.SZ 最新公告",
                            "002357 股价走势 目标价",
                        ]
                    },
                    {
                        "queries": [
                            "site:cninfo.com.cn 富临运业 002357 公告 业绩",
                            "site:szse.cn 富临运业 002357 监管 诉讼 风险",
                        ]
                    },
                ],
                "news_keyword_review": [
                    {"approved": True, "revision_notes": []},
                    {"approved": True, "revision_notes": []},
                ],
            }
        ),
        query_factory=QueryTemplateFactory(),
        max_review_rounds=2,
    )

    plan = workflow.build_plan(run_id="nar_test", target=target)

    assert plan.review_status == "approved"
    assert plan.fallback_used is False
    assert plan.queries == (
        "site:cninfo.com.cn 富临运业 002357 公告 业绩",
        "site:szse.cn 富临运业 002357 监管 诉讼 风险",
    )


def test_query_template_factory_prioritizes_official_event_queries() -> None:
    """Fallback queries should start from official disclosure sources."""
    target = _target()
    queries = [query.query for query in QueryTemplateFactory().build_queries(target)]

    assert queries[0] == "site:cninfo.com.cn 平安银行 000001 年报 年度报告 业绩"
    assert queries[1] == (
        "site:cninfo.com.cn 平安银行 000001 季报 一季报 半年报 三季报 业绩"
    )
    assert queries[2] == "site:szse.cn 平安银行 000001 业绩预告 业绩快报 公告"
    assert any("业绩说明会 投资者关系 公告 新闻" in query for query in queries)
    assert not any(
        "股价" in query or "走势" in query or "行情" in query or "评级" in query
        for query in queries
    )


def _target(
    *,
    security_id: str = "000001.SZ",
    name: str = "平安银行",
    aliases: tuple[str, ...] = ("平安",),
    industry_terms: tuple[str, ...] = ("银行",),
) -> NewsTarget:
    """Return one quant PASS target."""
    return NewsTarget(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        security_id=security_id,
        symbol=security_id,
        name=name,
        trigger_type=TargetTriggerType.QUANT_PASS,
        decision_at=datetime(2026, 6, 29, tzinfo=UTC),
        priority=100,
        aliases=aliases,
        industry_terms=industry_terms,
    )
