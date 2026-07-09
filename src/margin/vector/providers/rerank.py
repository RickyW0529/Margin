"""HTTP rerank provider adapters.

This module implements ``HTTPRerankProvider``, an adapter for Cohere-style
or OpenAI-compatible ``/rerank`` HTTP endpoints that score a list of
documents by relevance to a query.
"""

from __future__ import annotations

from typing import Any

from margin.core.provider import HealthCheckResult, ProviderDescriptor, ProviderStatus, ProviderType
from margin.news.models import utc_now


class HTTPRerankProvider:
    """Rerank provider for Cohere-style or OpenAI-compatible HTTP endpoints.."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the HTTP rerank provider.

        Args:
            api_key: str | None: .
            base_url: str | None: .
            model: str | None: .
            client: Any | None: .
            timeout: float: .

        Returns:
            None: .
        """
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or "rerank"
        self._timeout = timeout
        if not self._api_key:
            raise RuntimeError("Rerank API key is required")
        if not self._base_url:
            raise RuntimeError("Rerank base URL is required")
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        self._descriptor = ProviderDescriptor(
            name="http_rerank",
            version=self._model,
            provider_type=ProviderType.RERANK,
            capabilities=["rerank"],
            secret_refs=["rerank_api_key"],
            config={"base_url": self._base_url, "model": self._model},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return a relevance score for each document relative to the query.

        Args:
            query: str: .
            documents: list[str]: .

        Returns:
            list[float]: .
        """
        response = self._client.post(
            f"{self._base_url}/rerank",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "query": query, "documents": documents},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload.get("scores"), list):
            scores = [float(value) for value in payload["scores"]]
            if len(scores) != len(documents):
                raise RuntimeError("Malformed rerank response: score length mismatch")
            return scores

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("Malformed rerank response: missing results")
        scores = [0.0] * len(documents)
        for item in raw_results:
            index = int(item["index"])
            score = float(item.get("relevance_score", item.get("score", 0.0)))
            scores[index] = score
        return scores

    def healthcheck(self) -> HealthCheckResult:
        """Run a lightweight health check against the rerank endpoint.

        Returns:
            HealthCheckResult: .
        """
        try:
            self.rerank("healthcheck", ["ok"])
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
