"""OpenAI-compatible embedding provider.

This module implements ``OpenAIEmbeddingProvider``, an adapter that calls
OpenAI-compatible ``/embeddings`` endpoints (such as OpenAI, Azure OpenAI,
or compatible proxies) to obtain dense vector representations of text.
"""

from __future__ import annotations

from typing import Any

from margin.core.provider import HealthCheckResult, ProviderDescriptor, ProviderStatus, ProviderType
from margin.news.models import utc_now


class OpenAIEmbeddingProvider:
    """Embedding provider for OpenAI-compatible ``/embeddings`` APIs.."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        client: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the OpenAI-compatible embedding provider.

        Args:
            api_key: str | None: .
            base_url: str | None: .
            model: str | None: .
            dimension: int | None: .
            client: Any | None: .
            timeout: float: .

        Returns:
            None: .
        """
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or "text-embedding-3-small"
        self._dimension = int(dimension or 1536)
        self._timeout = timeout
        if not self._api_key:
            raise RuntimeError("Embedding API key is required")
        if not self._base_url:
            raise RuntimeError("Embedding base URL is required")
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        self._descriptor = ProviderDescriptor(
            name="openai_embedding",
            version=self._model,
            provider_type=ProviderType.EMBEDDING,
            capabilities=["embed", "embed_batch"],
            secret_refs=["embedding_api_key"],
            config={"base_url": self._base_url, "model": self._model, "dimension": self._dimension},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    @property
    def name(self) -> str:
        """Return the provider name.

        Returns:
            str: .
        """
        return self._descriptor.name

    @property
    def version(self) -> str:
        """Return the model version string.

        Returns:
            str: .
        """
        return self._model

    @property
    def dim(self) -> int:
        """Return the expected embedding dimension.

        Returns:
            int: .
        """
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: str: .

        Returns:
            list[float]: .
        """
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings in a single API call.

        Args:
            texts: list[str]: .

        Returns:
            list[list[float]]: .
        """
        response = self._client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise RuntimeError("Malformed embedding response: data length mismatch")
        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list):
                raise RuntimeError("Malformed embedding response: missing embedding")
            converted = [float(value) for value in vector]
            if len(converted) != self._dimension:
                raise ValueError(
                    "Embedding dimension mismatch: "
                    f"expected {self._dimension}, got {len(converted)}"
                )
            vectors.append(converted)
        return vectors

    def healthcheck(self) -> HealthCheckResult:
        """Run a lightweight health check against the embedding endpoint.

        Returns:
            HealthCheckResult: .
        """
        try:
            self.embed("healthcheck")
        except Exception as exc:
            return HealthCheckResult(
                provider_name=self.name,
                status=ProviderStatus.UNHEALTHY,
                checked_at=utc_now(),
                message=str(exc),
            )
        return HealthCheckResult(
            provider_name=self.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )
