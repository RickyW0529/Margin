"""Worker that consumes document outbox events into the persistent index."""

from __future__ import annotations

import inspect
from typing import Any

from margin.news.models import DocumentStatus, SourceLevel
from margin.news.repository import NewsRepository
from margin.vector.chunker import Chunker, StructuredChunker, infer_doc_type
from margin.vector.models import (
    ChunkSecurityLink,
    EmbeddingKey,
    IndexedDocument,
    TrustLevel,
)
from margin.vector.parsers.text import PlainTextParser
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
        markdown_parser: PlainTextParser | None = None,
    ) -> None:
        """Initialize the indexing runner.

        Args:
            news_repository: NewsRepository: .
            vector_repository: VectorRepository: .
            embedding_provider: Any: .
            chunker: Chunker | None: .
            markdown_parser: Parser for canonical normalized Markdown.

        Returns:
            None: .
        """
        self._news = news_repository
        self._vectors = vector_repository
        self._embedding = embedding_provider
        self._legacy_chunker = chunker
        self._markdown_parser = markdown_parser or PlainTextParser(
            parser_version="normalized-markdown-v1"
        )
        self._structured_chunker = StructuredChunker(
            parser_version=self._markdown_parser.parser_version,
        )

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
                chunks, links = self._chunk_normalized_markdown(event)
                vectors = self._embedding.embed_batch([chunk.content for chunk in chunks])
                provider_name = _provider_name(self._embedding)
                model_version = _provider_version(self._embedding)
                _upsert_chunks(self._vectors, chunks, links)
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
                self._record_indexed_document(
                    event=event,
                    chunks=chunks,
                    provider_name=provider_name,
                    model_version=model_version,
                )
                self._news.mark_outbox_delivered(message.outbox_id)
                indexed += len(chunks)
            except Exception as exc:  # noqa: BLE001
                self._news.mark_outbox_failed(
                    message.outbox_id,
                    f"{type(exc).__name__}: {exc}",
                )
        return indexed

    def _chunk_normalized_markdown(self, event):  # noqa: ANN001, ANN201
        """Chunk canonical Markdown while retaining full-document character spans."""
        if event.processing_status != DocumentStatus.READY or not (event.content or "").strip():
            return [], []
        if self._legacy_chunker is not None:
            chunks = self._legacy_chunker.chunk(event)
            links = _links_for_chunks(chunks, event.symbols)
            return chunks, links

        blocks = self._markdown_parser.parse(
            event.content.encode("utf-8"),
            source_url=event.source_url,
        )
        result = self._structured_chunker.chunk(
            document_id=event.document_id,
            content_hash=event.content_hash,
            blocks=blocks,
            security_ids=event.symbols,
            trust_level=_trust_level(event.source_level, event.doc_type),
            source_level=event.source_level,
            doc_type=infer_doc_type(event),
            published_at=event.published_at,
            available_at=event.available_at,
            source_url=event.source_url,
            source_name=event.source_name,
            snapshot_id=event.snapshot_id,
            snapshot_hash=event.snapshot_hash,
        )
        return list(result.chunks), list(result.links)

    def _record_indexed_document(
        self,
        *,
        event,
        chunks,
        provider_name: str,
        model_version: str,
    ) -> None:
        """Persist parser/chunk lineage when the repository exposes that boundary."""
        upsert = getattr(self._vectors, "upsert_indexed_document", None)
        if not callable(upsert):
            return
        upsert(
            IndexedDocument(
                document_id=event.document_id,
                event_id=event.event_id,
                parser_version=self._markdown_parser.parser_version,
                input_hash=event.content_hash,
                chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
                embedding_keys=tuple(
                    EmbeddingKey(
                        chunk_id=chunk.chunk_id,
                        provider_name=provider_name,
                        model_name=model_version,
                        model_version=model_version,
                    ).key_hash
                    for chunk in chunks
                ),
            )
        )


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


def _links_for_chunks(chunks, security_ids):  # noqa: ANN001, ANN201
    """Build symbol links for an explicitly injected legacy chunker."""
    return [
        ChunkSecurityLink(
            chunk_id=chunk.chunk_id,
            security_id=security_id,
            link_type="mentioned",
            confidence=1.0,
        )
        for chunk in chunks
        for security_id in security_ids
    ]


def _upsert_chunks(repository, chunks, links) -> int:  # noqa: ANN001, ANN201
    """Persist chunks with links while supporting older test/storage adapters."""
    method = repository.upsert_chunks
    parameters = inspect.signature(method).parameters.values()
    supports_links = any(
        parameter.name == "links" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if supports_links:
        return method(chunks, links=links)
    return method(chunks)


def _trust_level(source_level: SourceLevel, doc_type: str) -> TrustLevel:
    """Map canonical document provenance to prompt-safety trust."""
    if doc_type in {"user_file", "user_note"}:
        return TrustLevel.USER_SUPPLIED_CONTENT
    if source_level <= SourceLevel.L3:
        return TrustLevel.TRUSTED_OFFICIAL_CONTENT
    return TrustLevel.UNTRUSTED_SOURCE_CONTENT


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
