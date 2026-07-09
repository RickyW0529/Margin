"""Tests for the Tavily web search adapter.

These tests cover ``TavilySearchAdapter`` and verify that successful responses are
mapped into the provider result contract, HTTP errors are surfaced as runtime
errors, and malformed payloads fail cleanly before corrupting downstream state.
"""

from __future__ import annotations

import pytest

from margin.news.providers.tavily import (
    TavilyErrorCode,
    TavilyProviderError,
    TavilySearchAdapter,
)


class FakeResponse:
    """Stand-in HTTP response for unit testing the Tavily adapter.."""

    def __init__(self, status_code: int, payload: dict):
        """Initialize a fake response.

        Args:
            status_code: int: .
            payload: dict: .

        Returns:
            Any: .
        """
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        """Return the configured JSON payload.

        Returns:
            dict: .
        """
        return self._payload

    def raise_for_status(self) -> None:
        """Raise a runtime error when the status code indicates a client/server error.

        Returns:
            None: .
        """
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Stand-in HTTP client that records POST requests and returns a fixed response.."""

    def __init__(self, response: FakeResponse):
        """Initialize the fake client with a fixed response.

        Args:
            response: FakeResponse: .

        Returns:
            Any: .
        """
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        """Record a POST request and return the configured response.

        Args:
            url: str: .
            **kwargs: Any: .

        Returns:
            FakeResponse: .
        """
        self.requests.append({"url": url, **kwargs})
        return self.response


def test_tavily_adapter_maps_results_and_sends_auth_header():
    """Successful Tavily responses are mapped to the provider result contract.

    Returns:
        Any: .
    """
    client = FakeClient(
        FakeResponse(
            200,
            {
                "results": [
                    {
                        "url": "https://example.com/a",
                        "title": "A",
                        "content": "摘要 A",
                    }
                ]
            },
        )
    )
    adapter = TavilySearchAdapter(api_key="secret", client=client)

    results = adapter.search("平安银行 公告", max_results=3)

    assert results == [{"url": "https://example.com/a", "title": "A", "snippet": "摘要 A"}]
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert client.requests[0]["json"]["query"] == "平安银行 公告"
    assert client.requests[0]["json"]["max_results"] == 3


def test_tavily_adapter_reports_rate_limit():
    """HTTP 429 responses are surfaced as a runtime error mentioning the rate limit.

    Returns:
        Any: .
    """
    adapter = TavilySearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(429, {"error": "rate limit"})),
    )

    with pytest.raises(RuntimeError, match="rate limit"):
        adapter.search("query")


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [
        (432, TavilyErrorCode.BUDGET_EXCEEDED),
        (433, TavilyErrorCode.PAYGO_LIMIT_EXCEEDED),
    ],
)
def test_tavily_adapter_reports_account_budget_limits(
    status_code: int,
    error_code: TavilyErrorCode,
) -> None:
    """Plan and PayGo limits are non-retryable budget states, not bad responses.

    Args:
        status_code: int: .
        error_code: TavilyErrorCode: .

    Returns:
        None: .
    """
    adapter = TavilySearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(status_code, {"detail": {"error": "limit"}})),
    )

    with pytest.raises(TavilyProviderError) as captured:
        adapter.search("query")

    assert captured.value.code is error_code
    assert captured.value.retryable is False


def test_tavily_adapter_rejects_malformed_payload():
    """Malformed JSON payloads fail before corrupting audit records.

    Returns:
        Any: .
    """
    adapter = TavilySearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(200, {"unexpected": []})),
    )

    with pytest.raises(RuntimeError, match="Malformed Tavily response"):
        adapter.search("query")
