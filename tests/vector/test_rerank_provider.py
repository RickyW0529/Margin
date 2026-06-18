"""Tests for the HTTP rerank provider.

Verifies that ``HTTPRerankProvider`` accepts both Cohere-style ranked results and
OpenAI-style score arrays and normalizes them into a per-input score list.
"""

from __future__ import annotations

from margin.vector.providers.rerank import HTTPRerankProvider


class FakeResponse:
    """Stub HTTP response for the rerank provider tests.

    Attributes:
        status_code: HTTP status code (always 200 for these tests).
        text: raw response body as a string.
        _payload: dictionary returned by ``json()``.
    """

    def __init__(self, payload: dict):
        """Initialize a fake successful response.

        Args:
            payload: JSON body returned by ``json()``.
        """
        self.status_code = 200
        self._payload = payload
        self.text = str(payload)

    def json(self):
        """Return the parsed JSON payload."""
        return self._payload

    def raise_for_status(self):
        """No-op because the fake response always represents success."""
        return None


class FakeClient:
    """Stub HTTP client that returns a fixed response for every POST call."""

    def __init__(self, response: FakeResponse):
        """Initialize the fake client.

        Args:
            response: response to return on every POST request.
        """
        self.response = response

    def post(self, url: str, **kwargs):
        """Return the configured response without recording the call.

        Args:
            url: request URL.
            **kwargs: additional request arguments.

        Returns:
            FakeResponse: the configured response object.
        """
        return self.response


def test_rerank_provider_supports_cohere_response_shape():
    """Cohere-style ``results`` array must map relevance scores by original index."""
    provider = HTTPRerankProvider(
        api_key="secret",
        base_url="https://rerank.example/v1",
        model="rerank-demo",
        client=FakeClient(
            FakeResponse(
                {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.2},
                    ]
                }
            )
        ),
    )

    assert provider.rerank("现金流", ["低相关", "高相关"]) == [0.2, 0.9]


def test_rerank_provider_supports_openai_response_shape():
    """OpenAI-style ``scores`` array must be accepted as deterministic per-input scores."""
    provider = HTTPRerankProvider(
        api_key="secret",
        base_url="https://rerank.example/v1",
        model="rerank-demo",
        client=FakeClient(FakeResponse({"scores": [0.4, 0.8]})),
    )

    assert provider.rerank("现金流", ["a", "b"]) == [0.4, 0.8]
