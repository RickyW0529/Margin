"""HTTP rerank provider adapters.

This module implements ``HTTPRerankProvider``, an adapter for Cohere-style
or OpenAI-compatible ``/rerank`` HTTP endpoints that score a list of
documents by relevance to a query.
"""

from __future__ import annotations

import os
from typing import Any

from margin.core.provider import HealthCheckResult, ProviderDescriptor, ProviderStatus, ProviderType
from margin.news.models import utc_now


class HTTPRerankProvider:
    """Rerank provider for Cohere-style or OpenAI-compatible HTTP endpoints.

    The provider calls a ``/rerank`` endpoint to obtain relevance scores for a
    query-document pair list. It supports both the top-level ``scores`` response
    format and the ``results`` format with ``index`` and ``score`` fields.

    Attributes:
        _api_key: Bearer token used to authenticate API requests.
        _base_url: Base URL of the rerank endpoint.
        _model: Model identifier sent to the endpoint.
        _timeout: Request timeout in seconds.
        _client: HTTP client used to call the endpoint.
        _descriptor: Provider descriptor exposed by the ``descriptor`` property.
    """

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

        Configuration is resolved with the following precedence:
        1. Explicit arguments.
        2. Environment variables (``MARGIN_RERANK_*``).
        3. Sensible defaults for ``model``.

        Args:
            api_key: API key for the rerank endpoint. Defaults to
                ``MARGIN_RERANK_API_KEY``.
            base_url: Base URL of the rerank endpoint. Defaults to
                ``MARGIN_RERANK_BASE_URL``.
            model: Model identifier. Defaults to ``MARGIN_RERANK_MODEL`` or
                ``rerank``.
            client: Optional pre-configured HTTP client. If omitted, an ``httpx``
                client is created.
            timeout: Request timeout in seconds.

        Raises:
            RuntimeError: If ``api_key`` or ``base_url`` cannot be resolved.
        """
        self._api_key = api_key or os.getenv("MARGIN_RERANK_API_KEY")
        self._base_url = (base_url or os.getenv("MARGIN_RERANK_BASE_URL") or "").rstrip("/")
        self._model = model or os.getenv("MARGIN_RERANK_MODEL") or "rerank"
        self._timeout = timeout
        if not self._api_key:
            raise RuntimeError("MARGIN_RERANK_API_KEY is required")
        if not self._base_url:
            raise RuntimeError("MARGIN_RERANK_BASE_URL is required")
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        self._descriptor = ProviderDescriptor(
            name="http_rerank",
            version=self._model,
            provider_type=ProviderType.RERANK,
            capabilities=["rerank"],
            secret_refs=["MARGIN_RERANK_API_KEY"],
            config={"base_url": self._base_url, "model": self._model},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            A ``ProviderDescriptor`` describing name, version, type, capabilities,
            secret references, and configuration.
        """
        return self._descriptor

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return a relevance score for each document relative to the query.

        The method accepts two response shapes:
        - A top-level ``scores`` array in the same order as ``documents``.
        - A ``results`` array containing objects with ``index`` and either
          ``relevance_score`` or ``score``.

        Args:
            query: The plain-text query.
            documents: The list of plain-text documents to score.

        Returns:
            A list of relevance scores, one per document, in the original order.

        Raises:
            RuntimeError: If the response is malformed or the score count does not
                match the document count.
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

        Performs a trivial rerank request and reports whether it succeeds.

        Returns:
            A ``HealthCheckResult`` with status ``HEALTHY`` or ``UNHEALTHY`` and
            an optional error message.
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
