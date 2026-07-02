"""Tavily WebSearch adapter.

Provides a thin HTTP client around the Tavily search API and maps responses
into raw result dictionaries. Runtime configuration is supplied explicitly by
the provider runtime layer after it resolves encrypted database config.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.news.models import utc_now


class TavilyErrorCode(StrEnum):
    """Stable token-safe Tavily error codes.

    Attributes:
        RATE_LIMITED: Provider returned HTTP 429 (rate limit exceeded).
        BUDGET_EXCEEDED: Provider returned HTTP 432 (key or plan usage limit exceeded).
        PAYGO_LIMIT_EXCEEDED: Provider returned HTTP 433 (pay-as-you-go limit exceeded).
        AUTH_FAILED: Provider returned HTTP 401/403 (authentication failed).
        SERVER_ERROR: Provider returned HTTP 5xx (server error).
        BAD_RESPONSE: Provider returned a malformed or unexpected response.
    """

    RATE_LIMITED = "provider_429"
    BUDGET_EXCEEDED = "provider_budget_exceeded"
    PAYGO_LIMIT_EXCEEDED = "provider_paygo_limit_exceeded"
    AUTH_FAILED = "provider_auth_failed"
    SERVER_ERROR = "provider_5xx"
    BAD_RESPONSE = "provider_bad_response"


class TavilyProviderError(RuntimeError):
    """Token-safe Tavily provider error."""

    def __init__(
        self,
        *,
        code: TavilyErrorCode,
        retryable: bool,
        message: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            code: Stable error code.
            retryable: Whether the error is retryable.
            message: Human-readable error message.
            retry_after_seconds: Optional seconds to wait before retrying.
        """
        self.provider_name = "tavily_websearch"
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


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
            api_key: Tavily API key resolved by the caller.
            client: Optional pre-configured HTTP client. Defaults to a new ``httpx.Client``.
            base_url: Tavily search endpoint URL.
            timeout: Request timeout in seconds.

        Raises:
            RuntimeError: If no API key is available.
        """
        self._api_key = api_key
        if not self._api_key:
            raise RuntimeError("Tavily API key is required")
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
            secret_refs=["websearch_api_key"],
            config={"base_url": self._base_url},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ``ProviderDescriptor`` with metadata, capabilities, and secret refs.
        """
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
            raise TavilyProviderError(
                code=TavilyErrorCode.RATE_LIMITED,
                retryable=True,
                message="Tavily rate limit exceeded",
            )
        if response.status_code in (401, 403):
            raise TavilyProviderError(
                code=TavilyErrorCode.AUTH_FAILED,
                retryable=False,
                message="Tavily authentication failed",
            )
        if response.status_code == 432:
            raise TavilyProviderError(
                code=TavilyErrorCode.BUDGET_EXCEEDED,
                retryable=False,
                message="Tavily key or plan usage limit exceeded",
            )
        if response.status_code == 433:
            raise TavilyProviderError(
                code=TavilyErrorCode.PAYGO_LIMIT_EXCEEDED,
                retryable=False,
                message="Tavily pay-as-you-go limit exceeded",
            )
        if response.status_code >= 500:
            raise TavilyProviderError(
                code=TavilyErrorCode.SERVER_ERROR,
                retryable=True,
                message=f"Tavily server error: HTTP {response.status_code}",
            )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise TavilyProviderError(
                code=TavilyErrorCode.BAD_RESPONSE,
                retryable=False,
                message=f"Tavily search failed: HTTP {response.status_code}",
            ) from exc

        payload = response.json()
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise TavilyProviderError(
                code=TavilyErrorCode.BAD_RESPONSE,
                retryable=False,
                message="Malformed Tavily response: missing results list",
            )

        results: list[dict[str, str]] = []
        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                raise TavilyProviderError(
                    code=TavilyErrorCode.BAD_RESPONSE,
                    retryable=False,
                    message="Malformed Tavily response: result must be object",
                )
            results.append(
                {
                    "url": str(item.get("url") or ""),
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                }
            )
        return results

    def healthcheck(self) -> HealthCheckResult:
        """Run a real lightweight Tavily search health check.

        Returns:
            ``HealthCheckResult`` with HEALTHY status if the search succeeds, or UNHEALTHY
            with the error message otherwise.
        """
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
