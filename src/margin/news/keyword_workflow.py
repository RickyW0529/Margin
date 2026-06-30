"""Keyword writer/reviewer loop for agentic news acquisition."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from margin.news.agentic_models import NewsSearchPlan
from margin.news.agentic_prompts import (
    KEYWORD_PROMPT_VERSION,
    build_keyword_review_prompt,
    build_keyword_writer_prompt,
    keyword_review_schema,
    keyword_writer_schema,
)
from margin.news.models import NewsTarget
from margin.news.query_templates import QueryTemplateFactory

_NEWS_EVENT_TERMS = (
    "公告",
    "业绩",
    "年报",
    "年度报告",
    "季报",
    "季度报告",
    "一季报",
    "半年报",
    "三季报",
    "业绩预告",
    "业绩快报",
    "业绩说明会",
    "重大事项",
    "监管",
    "诉讼",
    "处罚",
    "风险",
    "合同",
    "订单",
    "中标",
    "回购",
    "减持",
    "增持",
    "停牌",
    "复牌",
    "调研",
    "投资者关系",
)
_FORBIDDEN_MARKET_TERMS = (
    "股票",
    "股价",
    "股价走势",
    "股票走势",
    "走势",
    "行情",
    "行情走势",
    "实时行情",
    "报价",
    "目标价",
    "评级",
    "买入",
    "卖出",
    "荐股",
    "涨停",
    "跌停",
    "资金流向",
    "技术分析",
    "估值分析",
    "投资价值",
    "机构评级",
    "分析师评级",
    "研报",
    "机构观点",
    "股吧",
    "市盈率",
    "市净率",
    "财务数据",
    "预测股价",
)
_OFFICIAL_SOURCE_TERMS = (
    "site:cninfo.com.cn",
    "site:szse.cn",
    "site:sse.com.cn",
    "site:bse.cn",
)


class KeywordWorkflow:
    """Generate reviewed WebSearch queries for a news target."""

    def __init__(
        self,
        *,
        llm_service: Any,
        query_factory: QueryTemplateFactory | None = None,
        max_review_rounds: int = 2,
    ) -> None:
        """Initialize the workflow.

        Args:
            llm_service: LLM service used for structured completion calls.
            query_factory: Optional query template factory for fallback plans. Defaults to
                a new ``QueryTemplateFactory``.
            max_review_rounds: Maximum number of writer/review revision rounds.
        """
        self._llm = llm_service
        self._query_factory = query_factory or QueryTemplateFactory()
        self._max_review_rounds = max(1, max_review_rounds)

    def build_plan(self, *, run_id: str, target: NewsTarget) -> NewsSearchPlan:
        """Return an approved or deterministic fallback search plan.

        Runs the keyword writer/reviewer loop up to ``max_review_rounds`` times. If the
        LLM fails or the reviewer never approves, a deterministic fallback plan is
        returned.

        Args:
            run_id: Identifier of the agentic news acquisition run.
            target: News target to build queries for.

        Returns:
            A ``NewsSearchPlan`` with review_status "approved" or "fallback".
        """
        revision_notes: tuple[str, ...] = ()
        last_prompt_hash = ""
        last_response_hash: str | None = None
        for _ in range(self._max_review_rounds):
            writer_prompt = build_keyword_writer_prompt(target, revision_notes)
            writer_response = self._llm.complete_structured(
                prompt=writer_prompt,
                output_schema=keyword_writer_schema(),
                task_type="websearch",
                node_name=writer_prompt.node_name,
                graph_run_id=run_id,
            )
            last_prompt_hash = writer_prompt.prompt_hash
            if not getattr(writer_response, "success", False):
                break
            output = dict(getattr(writer_response, "output", {}) or {})
            last_response_hash = _hash_json(output)
            queries = _clean_queries(output.get("queries", ()))
            if not queries:
                break
            review_prompt = build_keyword_review_prompt(target, queries)
            review_response = self._llm.complete_structured(
                prompt=review_prompt,
                output_schema=keyword_review_schema(),
                task_type="validation",
                node_name=review_prompt.node_name,
                graph_run_id=run_id,
            )
            last_prompt_hash = review_prompt.prompt_hash
            if not getattr(review_response, "success", False):
                break
            review_output = dict(getattr(review_response, "output", {}) or {})
            last_response_hash = _hash_json(review_output)
            guardrail_notes = _guardrail_review(target, queries)
            if bool(review_output.get("approved")) and not guardrail_notes:
                return NewsSearchPlan(
                    plan_id=_plan_id(run_id, target.security_id),
                    run_id=run_id,
                    security_id=target.security_id,
                    symbol=target.symbol,
                    name=target.name,
                    queries=queries,
                    review_status="approved",
                    fallback_used=False,
                    prompt_version=KEYWORD_PROMPT_VERSION,
                    prompt_hash=last_prompt_hash,
                    response_hash=last_response_hash,
                )
            revision_notes = tuple(
                str(note)
                for note in (*review_output.get("revision_notes", ()), *guardrail_notes)
                if str(note).strip()
            )
        return self._fallback_plan(
            run_id=run_id,
            target=target,
            prompt_hash=last_prompt_hash,
            response_hash=last_response_hash,
        )

    def _fallback_plan(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        prompt_hash: str,
        response_hash: str | None,
    ) -> NewsSearchPlan:
        """Build a deterministic fallback search plan."""
        queries = tuple(query.query for query in self._query_factory.build_queries(target))
        return NewsSearchPlan(
            plan_id=_plan_id(run_id, target.security_id),
            run_id=run_id,
            security_id=target.security_id,
            symbol=target.symbol,
            name=target.name,
            queries=queries,
            review_status="fallback",
            fallback_used=True,
            prompt_version=KEYWORD_PROMPT_VERSION,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
        )


def _clean_queries(value: Any) -> tuple[str, ...]:
    """Normalize model output into unique non-empty queries."""
    queries: list[str] = []
    for item in value or ():
        query = str(item).strip()
        if query and query not in queries:
            queries.append(query)
    return tuple(queries[:4])


def _guardrail_review(target: NewsTarget, queries: tuple[str, ...]) -> tuple[str, ...]:
    """Return local review notes for unsafe or low-quality search queries."""
    notes: list[str] = []
    if not queries:
        return ("missing queries",)
    company_terms = _company_terms(target)
    ticker_terms = _ticker_terms(target)
    has_official_source = any(
        source in query.lower()
        for query in queries
        for source in _OFFICIAL_SOURCE_TERMS
    )
    if not has_official_source:
        notes.append("query plan missing official disclosure source")
    for query in queries:
        if not any(term in query for term in company_terms):
            notes.append(f"query missing target company name: {query}")
        if not any(term in query for term in ticker_terms):
            notes.append(f"query missing target ticker: {query}")
        if not any(term in query for term in _NEWS_EVENT_TERMS):
            notes.append(f"query missing concrete news event term: {query}")
        forbidden = [term for term in _FORBIDDEN_MARKET_TERMS if term in query]
        if forbidden:
            notes.append(
                f"query contains market/trading terms {','.join(forbidden)}: {query}"
            )
    return tuple(notes)


def _company_terms(target: NewsTarget) -> tuple[str, ...]:
    """Return accepted company identifiers for keyword review."""
    terms = [target.name, *target.aliases]
    return tuple(term for term in _unique_texts(*terms) if term != target.security_id)


def _ticker_terms(target: NewsTarget) -> tuple[str, ...]:
    """Return accepted ticker variants for keyword review."""
    raw = target.symbol or target.security_id
    numeric = raw.split(".")[0]
    return _unique_texts(raw, target.security_id, numeric)


def _unique_texts(*values: Any) -> tuple[str, ...]:
    """Return unique non-empty text values, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _plan_id(run_id: str, security_id: str) -> str:
    """Return a stable plan id for a run/security pair."""
    digest = hashlib.sha256(f"{run_id}|{security_id}".encode()).hexdigest()
    return f"nsp_{digest[:24]}"


def _hash_json(value: Any) -> str:
    """Hash a JSON-serializable value."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
