"""Firecrawl ToolCatalog registration and handler boundary tests."""

from __future__ import annotations

from types import SimpleNamespace

from margin.agents.tools.catalog import default_tool_catalog
from margin.news.providers.firecrawl import FirecrawlErrorCode, FirecrawlProviderError


class _FirecrawlAdapter:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.scrape_calls: list[dict[str, object]] = []

    def search(self, query: str, max_results: int, *, sources: object) -> list[dict[str, str]]:
        self.search_calls.append(
            {"query": query, "max_results": max_results, "sources": sources}
        )
        return [{"url": "https://example.com", "title": "Example", "snippet": "摘要"}]

    def scrape(
        self,
        url: str,
        *,
        only_main_content: bool,
        max_chars: int,
    ) -> dict[str, object]:
        self.scrape_calls.append(
            {
                "url": url,
                "only_main_content": only_main_content,
                "max_chars": max_chars,
            }
        )
        return {
            "url": url,
            "title": "Example",
            "markdown": "# Example",
            "char_count": 9,
            "truncated": False,
            "safe_summary": "Scraped Example.",
        }


class _RateLimitedAdapter(_FirecrawlAdapter):
    def search(self, query: str, max_results: int, *, sources: object) -> list[dict[str, str]]:
        del query, max_results, sources
        raise FirecrawlProviderError(
            code=FirecrawlErrorCode.RATE_LIMITED,
            retryable=True,
            message="Firecrawl search rate limit exceeded",
            retry_after_seconds=9,
        )


def test_default_catalog_registers_and_executes_firecrawl_tools() -> None:
    adapter = _FirecrawlAdapter()
    catalog = default_tool_catalog(firecrawl_adapter=adapter)

    search = catalog.get("firecrawl.search", "v1")
    scrape = catalog.get("firecrawl.scrape", "v1")

    assert search is not None
    assert scrape is not None
    assert search.spec.input_schema["properties"]["query"]["maxLength"] == 500
    search_output = search.handler(
        SimpleNamespace(
            input_json={
                "query": "宁德时代",
                "max_results": 3,
                "sources": ["web", "news"],
            }
        )
    )
    scrape_output = scrape.handler(
        SimpleNamespace(
            input_json={
                "url": "https://example.com",
                "only_main_content": True,
                "max_chars": 2048,
            }
        )
    )

    assert search_output["status"] == "ready"
    assert search_output["result_count"] == 1
    assert adapter.search_calls == [
        {
            "query": "宁德时代",
            "max_results": 3,
            "sources": ("web", "news"),
        }
    ]
    assert scrape_output["status"] == "ready"
    assert scrape_output["markdown"] == "# Example"
    assert adapter.scrape_calls[0]["max_chars"] == 2048


def test_firecrawl_tool_error_preserves_retry_metadata() -> None:
    catalog = default_tool_catalog(firecrawl_adapter=_RateLimitedAdapter())
    search = catalog.get("firecrawl.search", "v1")
    assert search is not None

    output = search.handler(
        SimpleNamespace(input_json={"query": "测试", "sources": ["web"]})
    )

    assert output["status"] == "error"
    assert output["error_code"] == "provider_429"
    assert output["retryable"] is True
    assert output["retry_after_seconds"] == 9
