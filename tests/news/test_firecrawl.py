"""Firecrawl adapter: search contract, scrape truncation, and SSRF guard."""

from __future__ import annotations

import pytest

from margin.news.providers.firecrawl import (
    FirecrawlErrorCode,
    FirecrawlProviderError,
    FirecrawlSearchAdapter,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict,
        *,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return self.response


def test_search_maps_v2_results_to_provider_contract():
    """Web/news hits become the shared {url, title, snippet} search contract."""
    client = FakeClient(
        FakeResponse(
            200,
            {
                "data": {
                    "web": [
                        {
                            "url": "https://example.com/a",
                            "title": "A",
                            "description": "摘要 A",
                        }
                    ],
                    "news": [
                        {
                            "url": "https://news.example.com/b",
                            "title": "B",
                            "snippet": "摘要 B",
                        }
                    ],
                },
            },
        )
    )
    adapter = FirecrawlSearchAdapter(api_key="secret", client=client)

    results = adapter.search("宁德时代 舆情", max_results=5)

    assert results == [
        {"url": "https://example.com/a", "title": "A", "snippet": "摘要 A"},
        {"url": "https://news.example.com/b", "title": "B", "snippet": "摘要 B"},
    ]
    assert client.requests[0]["url"].endswith("/v2/search")
    assert client.requests[0]["json"]["limit"] == 5
    assert client.requests[0]["json"]["sources"] == ["web", "news"]


def test_search_accepts_empty_v2_source_buckets():
    """An empty source array is a valid search response, not malformed JSON."""
    client = FakeClient(FakeResponse(200, {"success": True, "data": {"web": []}}))
    adapter = FirecrawlSearchAdapter(api_key="secret", client=client)

    assert adapter.search("没有命中的查询", sources=("web",)) == []
    assert client.requests[0]["json"]["sources"] == ["web"]


def test_search_rejects_unsuccessful_200_envelope():
    """Firecrawl success=false envelopes must not become successful empty results."""
    client = FakeClient(
        FakeResponse(200, {"success": False, "error": "search execution failed"})
    )
    adapter = FirecrawlSearchAdapter(api_key="secret", client=client)

    with pytest.raises(FirecrawlProviderError) as captured:
        adapter.search("测试")

    assert captured.value.code is FirecrawlErrorCode.BAD_RESPONSE


def test_scrape_truncates_markdown_for_agent_context():
    """Long page bodies are clipped so tool output stays bounded."""
    client = FakeClient(
        FakeResponse(
            200,
            {
                "data": {
                    "markdown": "hello world " * 100,
                    "metadata": {
                        "title": "Example",
                        "url": "https://example.com/article",
                    },
                },
            },
        )
    )
    adapter = FirecrawlSearchAdapter(api_key="secret", client=client, resolve_dns=False)

    result = adapter.scrape("https://example.com/article", max_chars=40)

    assert result["title"] == "Example"
    assert result["truncated"] is True
    assert len(result["markdown"]) == 40
    assert client.requests[0]["json"]["formats"] == ["markdown"]


def test_scrape_rejects_private_urls_before_http():
    """SSRF guard must run before any outbound scrape request."""
    client = FakeClient(FakeResponse(200, {"data": {"markdown": "x"}}))
    adapter = FirecrawlSearchAdapter(
        api_key="secret",
        client=client,
        resolve_dns=False,
    )

    with pytest.raises(FirecrawlProviderError) as captured:
        adapter.scrape("http://127.0.0.1/internal")

    assert captured.value.code is FirecrawlErrorCode.SSRF_BLOCKED
    assert client.requests == []


def test_search_timeout_is_retryable():
    """The documented HTTP 408 response should retain retry semantics."""
    adapter = FirecrawlSearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(408, {"error": "timeout"})),
    )

    with pytest.raises(FirecrawlProviderError) as captured:
        adapter.search("测试")

    assert captured.value.code is FirecrawlErrorCode.TIMEOUT
    assert captured.value.retryable is True


def test_rate_limit_preserves_retry_after_header():
    """Retry scheduling should honor Firecrawl's documented Retry-After seconds."""
    adapter = FirecrawlSearchAdapter(
        api_key="secret",
        client=FakeClient(
            FakeResponse(
                429,
                {"success": False, "error": "rate limit exceeded"},
                headers={"Retry-After": "7"},
            )
        ),
    )

    with pytest.raises(FirecrawlProviderError) as captured:
        adapter.search("测试")

    assert captured.value.code is FirecrawlErrorCode.RATE_LIMITED
    assert captured.value.retry_after_seconds == 7
