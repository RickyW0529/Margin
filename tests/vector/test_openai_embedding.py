"""Tests for the OpenAI-compatible embedding provider.

Uses fake HTTP clients to verify request shape, batching, authentication header
injection, and dimension validation without calling a live API.
"""

from __future__ import annotations

import pytest

from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider


class FakeResponse:
    """Stub HTTP response for the embedding provider tests.."""

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

    def json(self):
        """Return the parsed JSON payload.

        Returns:
            Any: .
        """
        return self._payload

    def raise_for_status(self):
        """Raise a runtime error when the status code indicates failure.

        Returns:
            Any: .
        """
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Stub HTTP client that records all POST calls and returns a fixed response.."""

    def __init__(self, response: FakeResponse):
        """Initialize the fake client.

        Args:
            response: FakeResponse: .

        Returns:
            Any: .
        """
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs):
        """Record the request and return the configured response.

        Args:
            url: str: .
            **kwargs: Any: .

        Returns:
            Any: .
        """
        self.requests.append({"url": url, **kwargs})
        return self.response


def test_openai_embedding_provider_batches_and_validates_dimensions():
    """Provider must send batched inputs with auth headers and validate vector length.
    Returns:.

    Returns:
        Any: .
    """
    client = FakeClient(
        FakeResponse(
            200,
            {"data": [{"embedding": [1, 0, 0]}, {"embedding": [0, 1, 0]}]},
        )
    )
    provider = OpenAIEmbeddingProvider(
        api_key="secret",
        base_url="https://llm.example/v1",
        model="embed-demo",
        dimension=3,
        client=client,
    )

    vectors = provider.embed_batch(["a", "b"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert client.requests[0]["url"] == "https://llm.example/v1/embeddings"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert client.requests[0]["json"]["model"] == "embed-demo"


def test_openai_embedding_provider_rejects_malformed_vectors():
    """Provider must reject embeddings whose length does not match the dimension.

    Returns:
        Any: .
    """
    provider = OpenAIEmbeddingProvider(
        api_key="secret",
        base_url="https://llm.example/v1",
        model="embed-demo",
        dimension=3,
        client=FakeClient(FakeResponse(200, {"data": [{"embedding": [1, 2]}]})),
    )

    with pytest.raises(ValueError, match="dimension"):
        provider.embed("bad")
