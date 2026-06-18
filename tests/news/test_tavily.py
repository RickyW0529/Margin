"""Tests for the Tavily web search adapter.

These tests cover ``TavilySearchAdapter`` and verify that successful responses are
mapped into the provider result contract, HTTP errors are surfaced as runtime
errors, and malformed payloads fail cleanly before corrupting downstream state.
"""

from __future__ import annotations

import pytest

from margin.news.providers.tavily import TavilySearchAdapter


class FakeResponse:
    """Stand-in HTTP response for unit testing the Tavily adapter.

    Attributes:
        status_code: The HTTP status code to report.
        text: String representation of the response payload.
        _payload: The parsed JSON payload returned by ``json()``.
    """

    def __init__(self, status_code: int, payload: dict):
        """Initialize a fake response.

        Args:
            status_code: HTTP status code to return.
            payload: JSON payload to return from ``json()``.
        """
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        """Return the configured JSON payload.

        Returns:
            The fake response payload as a dictionary.
        """
        return self._payload

    def raise_for_status(self) -> None:
        """Raise a runtime error when the status code indicates a client/server error.

        Raises:
            RuntimeError: If ``status_code`` is 400 or greater.
        """
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Stand-in HTTP client that records POST requests and returns a fixed response.

    Attributes:
        response: The ``FakeResponse`` instance returned by every ``post`` call.
        requests: List of keyword arguments passed to each ``post`` invocation.
    """

    def __init__(self, response: FakeResponse):
        """Initialize the fake client with a fixed response.

        Args:
            response: The response to return for all POST requests.
        """
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        """Record a POST request and return the configured response.

        Args:
            url: The request URL.
            **kwargs: Additional request arguments (headers, json payload, etc.).

        Returns:
            The configured ``FakeResponse`` instance.
        """
        self.requests.append({"url": url, **kwargs})
        return self.response


def test_tavily_adapter_maps_results_and_sends_auth_header():
    """Successful Tavily responses are mapped to the provider result contract.

    Verifies that:
    - result fields are renamed from ``content`` to ``snippet``;
    - the Authorization header contains a Bearer token;
    - the query and max_results parameters are sent in the JSON body.
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

    assert results == [
        {"url": "https://example.com/a", "title": "A", "snippet": "摘要 A"}
    ]
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert client.requests[0]["json"]["query"] == "平安银行 公告"
    assert client.requests[0]["json"]["max_results"] == 3


def test_tavily_adapter_reports_rate_limit():
    """HTTP 429 responses are surfaced as a runtime error mentioning the rate limit.

    Verifies that ``search`` raises ``RuntimeError`` when the Tavily API returns
    a rate-limit status code.
    """
    adapter = TavilySearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(429, {"error": "rate limit"})),
    )

    with pytest.raises(RuntimeError, match="rate limit"):
        adapter.search("query")


def test_tavily_adapter_rejects_malformed_payload():
    """Malformed JSON payloads fail before corrupting audit records.

    Verifies that ``search`` raises ``RuntimeError`` when the response body does
    not contain the expected ``results`` field.
    """
    adapter = TavilySearchAdapter(
        api_key="secret",
        client=FakeClient(FakeResponse(200, {"unexpected": []})),
    )

    with pytest.raises(RuntimeError, match="Malformed Tavily response"):
        adapter.search("query")
