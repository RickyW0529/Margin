"""Worker that consumes document outbox events into the persistent index."""

from __future__ import annotations

from typing import Any

from margin.news.repository import NewsRepository
from margin.vector.chunker import Chunker
from margin.vector.repository import VectorRepository


class DocumentIndexingRunner:
    """Connect module 03 document events to module 04 chunks/embeddings.."""

    def __init__(
        self,
        *,
        news_repository: NewsRepository,
        vector_repository: VectorRepository,
        embedding_provider: Any,
        chunker: Chunker | None = None,
    ) -> None:
        """Initialize the indexing runner.

        Args:
            news_repository: NewsRepository: .
            vector_repository: VectorRepository: .
            embedding_provider: Any: .
            chunker: Chunker | None: .

        Returns:
            None: .
        """
        self._news = news_repository
        self._vectors = vector_repository
        self._embedding = embedding_provider
        self._chunker = chunker or Chunker()

    def run_once(self, *, limit: int = 50) -> int:
        """Consume one batch of vector-index outbox messages.

        Args:
            limit: int: .

        Returns:
            int: .
        """
        indexed = 0
        for message in self._news.claim_outbox("vector_index", limit):
            try:
                event = self._news.get_document_event(message.event_id)
                if event is None:
                    raise KeyError(f"document event '{message.event_id}' not found")
                chunks = self._chunker.chunk(event)
                vectors = self._embedding.embed_batch([chunk.content for chunk in chunks])
                provider_name = _provider_name(self._embedding)
                model_version = _provider_version(self._embedding)
                self._vectors.upsert_chunks(chunks)
                vector_count = self._vectors.upsert_embeddings(
                    [
                        (chunk.chunk_id, vector)
                        for chunk, vector in zip(chunks, vectors, strict=True)
                    ],
                    provider_name=provider_name,
                    model_name=model_version,
                    model_version=model_version,
                )
                self._vectors.record_index_audit(
                    operation="outbox_index",
                    provider_name=provider_name,
                    model_name=model_version,
                    model_version=model_version,
                    chunk_count=len(chunks),
                    vector_count=vector_count,
                    keyword_count=len(chunks),
                    degraded=vector_count != len(chunks),
                )
                self._news.mark_outbox_delivered(message.outbox_id)
                indexed += len(chunks)
            except Exception as exc:  # noqa: BLE001
                self._news.mark_outbox_failed(
                    message.outbox_id,
                    f"{type(exc).__name__}: {exc}",
                )
        return indexed


class IndexingRunner:
    """Lease-aware v0.2 runner for durable vector-index outbox recovery.."""

    def __init__(
        self,
        *,
        news_repository: NewsRepository,
        pipeline: Any,
        lease_seconds: int = 300,
    ) -> None:
        """Initialize the lease-aware indexing runner.

        Args:
            news_repository: NewsRepository: .
            pipeline: Any: .
            lease_seconds: int: .

        Returns:
            None: .
        """
        self._news = news_repository
        self._pipeline = pipeline
        self._lease_seconds = lease_seconds

    def claim_next(self, *, now=None):  # noqa: ANN001, ANN201
        """Claim one eligible outbox row.

        Args:
            now: Any: .

        Returns:
            Any: .
        """
        claimed = self._news.claim_outbox_with_lease(
            "vector_index",
            limit=1,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        return claimed[0] if claimed else None

    def process_one(self, *, event_id: str) -> None:
        """Process one document event and preserve retryability on provider failure.

        Args:
            event_id: str: .

        Returns:
            None: .
        """
        row = self._news.get_outbox_by_event(event_id, "vector_index")
        if row is None:
            return
        if row.status != "processing":
            claimed = self.claim_next()
            if claimed is None:
                return
            row = claimed
        try:
            event = self._news.get_document_event(event_id)
            if event is None:
                raise KeyError(f"document event '{event_id}' not found")
            self._pipeline.index_event(event)
            self._news.mark_outbox_succeeded(row.outbox_id)
        except Exception as exc:  # noqa: BLE001
            self._news.mark_outbox_retryable(
                row.outbox_id,
                f"{type(exc).__name__}: {exc}",
            )


def _provider_name(provider: Any) -> str:
    """Return the provider's canonical name.

    Args:
        provider: Any: .

    Returns:
        str: .
    """
    value = getattr(provider, "name", None)
    if value:
        return str(value)
    return str(provider.descriptor.name)


def _provider_version(provider: Any) -> str:
    """Return the provider's version string.

    Args:
        provider: Any: .

    Returns:
        str: .
    """
    value = getattr(provider, "version", None)
    if value:
        return str(value)
    return str(provider.descriptor.version)
