"""Tavily WebSearch adapter.

Provides a thin HTTP client around the Tavily search API and maps responses into a simple
list of raw result dictionaries. The adapter expects the API key to be supplied explicitly or
via the ``MARGIN_WEBSEARCH_API_KEY`` environment variable.
"""

from __future__ import annotations

import os
from typing import Any

from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.news.models import utc_now


class TavilySearchAdapter:
    """Adapter mapping Tavily HTTP responses into Margin raw search results.

    Performs synchronous HTTP calls to the Tavily search endpoint. Results are returned as
    dictionaries compatible with the ``WebSearchProvider.search_func`` contract.

    Attributes:
        _api_key: Tavily API key used for authentication.
        _client: HTTP client used to make requests.
        _base_url: Tavily search endpoint URL.
        _timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        base_url: str = "https://api.tavily.com/search",
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Tavily search adapter.

        Args:
            api_key: Tavily API key. If omitted, read from ``MARGIN_WEBSEARCH_API_KEY``.
            client: Optional pre-configured HTTP client. Defaults to a new ``httpx.Client``.
            base_url: Tavily search endpoint URL.
            timeout: Request timeout in seconds.

        Raises:
            RuntimeError: If no API key is available.
        """
        self._api_key = api_key or os.getenv("MARGIN_WEBSEARCH_API_KEY")
        if not self._api_key:
            raise RuntimeError("MARGIN_WEBSEARCH_API_KEY is required for Tavily")
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        self._base_url = base_url
        self._timeout = timeout
        self._descriptor = ProviderDescriptor(
            name="tavily_websearch",
            version="tavily_search",
            provider_type=ProviderType.WEB_SEARCH,
            capabilities=["search"],
            secret_refs=["MARGIN_WEBSEARCH_API_KEY"],
            config={"base_url": self._base_url},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor."""
        return self._descriptor

    def search(self, query: str, max_results: int = 10) -> list[dict[str, str]]:
        """Execute a Tavily search and return raw result dictionaries.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of raw search result dictionaries containing ``url``, ``title``, and
            ``snippet``.

        Raises:
            RuntimeError: If the request fails, the rate limit is exceeded, or the response
                is malformed.
        """
        response = self._client.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=self._timeout,
        )
        if response.status_code == 429:
            raise RuntimeError("Tavily rate limit exceeded")
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        payload = response.json()
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("Malformed Tavily response: missing results list")

        results: list[dict[str, str]] = []
        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                raise RuntimeError("Malformed Tavily response: result must be object")
            results.append(
                {
                    "url": str(item.get("url") or ""),
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                }
            )
        return results

    def healthcheck(self) -> HealthCheckResult:
        """Run a real lightweight Tavily search health check."""
        try:
            self.search("healthcheck", max_results=1)
        except Exception as exc:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.UNHEALTHY,
                checked_at=utc_now(),
                message=str(exc),
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )
