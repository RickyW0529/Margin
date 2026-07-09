"""Versioned query templates for target-driven news WebSearch."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from margin.news.models import NewsTarget


class GeneratedSearchQuery(BaseModel):
    """Concrete search query plus template audit metadata.."""

    query: str
    template_version: str
    template_hash: str
    target_dedupe_key: str
    max_results: int = 5

    model_config = {"frozen": True}


class QueryTemplateVersion(BaseModel):
    """Versioned configuration for deterministic query generation.."""

    version: str = "news-query-v0.4.0"
    event_terms: tuple[str, ...] = (
        "业绩",
        "公告",
        "年报",
        "年度报告",
        "季报",
        "季度报告",
        "业绩预告",
        "业绩快报",
        "业绩说明会",
    )
    lookback_days: int = 2
    max_results_per_query: int = 5

    @property
    def config_hash(self) -> str:
        """Stable hash of the template config.

        Returns:
            str: .
        """
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class QueryTemplateFactory:
    """Build audited WebSearch queries for one refresh target.."""

    def __init__(self, version: QueryTemplateVersion | None = None) -> None:
        """Initialize the instance.

        Args:
            version: QueryTemplateVersion | None: .

        Returns:
            None: .
        """
        self.version = version or QueryTemplateVersion()

    def build_queries(self, target: NewsTarget) -> list[GeneratedSearchQuery]:
        """Generate deterministic company/event queries for a target.

        Args:
            target: NewsTarget: .

        Returns:
            list[GeneratedSearchQuery]: .
        """
        company = target.name
        ticker = target.security_id.split(".", maxsplit=1)[0]
        exchange_domain = _exchange_disclosure_domain(target.security_id)
        template_hash = self.version.config_hash
        queries = [
            f"site:cninfo.com.cn {company} {ticker} 年报 年度报告 业绩",
            f"site:cninfo.com.cn {company} {ticker} 季报 一季报 半年报 三季报 业绩",
            f"site:{exchange_domain} {company} {ticker} 业绩预告 业绩快报 公告",
            f"{company} {ticker} 业绩说明会 投资者关系 公告 新闻",
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


def _exchange_disclosure_domain(security_id: str) -> str:
    """Return the exchange disclosure domain for a security id.

    Args:
        security_id: str: .

    Returns:
        str: .
    """
    suffix = security_id.rsplit(".", maxsplit=1)[-1].upper()
    if suffix == "SH":
        return "sse.com.cn"
    if suffix == "BJ":
        return "bse.cn"
    return "szse.cn"


__all__ = [
    "GeneratedSearchQuery",
    "QueryTemplateFactory",
    "QueryTemplateVersion",
]
