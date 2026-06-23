"""Versioned query templates for target-driven news WebSearch."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from margin.news.models import NewsTarget


class GeneratedSearchQuery(BaseModel):
    """Concrete search query plus template audit metadata."""

    query: str
    template_version: str
    template_hash: str
    target_dedupe_key: str
    max_results: int = 5

    model_config = {"frozen": True}


class QueryTemplateVersion(BaseModel):
    """Versioned configuration for deterministic query generation."""

    version: str = "news-query-v0.2.0"
    event_terms: tuple[str, ...] = (
        "业绩",
        "公告",
        "监管",
        "诉讼",
        "合同",
        "减持",
        "回购",
        "停牌",
        "复牌",
    )
    lookback_days: int = 2
    max_results_per_query: int = 5

    @property
    def config_hash(self) -> str:
        """Stable hash of the template config."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class QueryTemplateFactory:
    """Build audited WebSearch queries for one refresh target."""

    def __init__(self, version: QueryTemplateVersion | None = None) -> None:
        """Initialize the instance."""
        self.version = version or QueryTemplateVersion()

    def build_queries(self, target: NewsTarget) -> list[GeneratedSearchQuery]:
        """Generate deterministic company/event queries for a target."""
        base_terms = [target.name, target.symbol, *target.aliases]
        event_terms = " OR ".join(self.version.event_terms[:4])
        industry_terms = " ".join(target.industry_terms[:2])
        template_hash = self.version.config_hash
        queries = [
            f"{base_terms[0]} {event_terms}",
            " ".join(term for term in [target.symbol, target.name, industry_terms] if term),
        ]
        return [
            GeneratedSearchQuery(
                query=query,
                template_version=self.version.version,
                template_hash=template_hash,
                target_dedupe_key=target.dedupe_key,
                max_results=self.version.max_results_per_query,
            )
            for query in queries
        ]


__all__ = [
    "GeneratedSearchQuery",
    "QueryTemplateFactory",
    "QueryTemplateVersion",
]
