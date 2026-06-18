"""PostgreSQL/pgvector repository for chunks, embeddings, and retrieval replay.

This module provides ``VectorRepository``, the primary persistence boundary for
chunk metadata, dense embeddings, indexing audit records, and replayable
retrieval audit records. It performs in-process cosine scoring because
pgvector's native distance operators are not used directly here.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.news.models import SourceLevel, utc_now
from margin.vector.db_models import (
    ChunkEmbeddingRow,
    ChunkRow,
    IndexAuditRecordRow,
    RetrievalAuditRecordRow,
)
from margin.vector.models import Chunk, DocType, RetrievalResult


class VectorRepository:
    """Persistent chunk/vector/audit boundary.

    ``VectorRepository`` exposes CRUD and search methods that translate between
    the domain models defined in ``margin.vector.models`` and the SQLAlchemy rows
    defined in ``margin.vector.db_models``. All public methods use the supplied
    session factory for transaction/connection management.

    Attributes:
        _session_factory: Callable that returns a new SQLAlchemy ``Session``.
        _dimension: Expected dimensionality of stored and query vectors.
    """

    def __init__(self, session_factory: Callable[[], Session], *, dimension: int) -> None:
        """Initialize a new repository instance.

        Args:
            session_factory: Callable that returns a configured SQLAlchemy
                ``Session``. The callable is expected to support both ``begin()``
                and direct call usage.
            dimension: Expected vector dimension. Used to validate embeddings and
                query vectors.
        """
        self._session_factory = session_factory
        self._dimension = dimension

    def upsert_chunks(self, chunks: list[Chunk]) -> int:
        """Persist chunk metadata idempotently.

        Inserts new chunks or updates existing rows by ``chunk_id``.

        Args:
            chunks: List of ``Chunk`` domain objects to persist.

        Returns:
            The number of chunks processed.
        """
        with self._session_factory.begin() as session:
            for chunk in chunks:
                row = session.get(ChunkRow, chunk.chunk_id)
                if row is None:
                    session.add(_chunk_to_row(chunk))
                else:
                    _update_chunk_row(row, chunk)
        return len(chunks)

    def upsert_embeddings(
        self,
        items: list[tuple[str, list[float]]],
        *,
        provider_name: str,
        model_name: str,
        model_version: str,
    ) -> int:
        """Persist model-versioned embeddings idempotently.

        Inserts or updates embedding rows keyed by ``chunk_id``, ``provider_name``,
        ``model_name``, and ``model_version``. Each vector is validated against the
        configured dimension.

        Args:
            items: Tuples of ``(chunk_id, vector)`` to persist.
            provider_name: Name of the embedding provider.
            model_name: Name of the embedding model.
            model_version: Version of the embedding model.

        Returns:
            The number of embedding rows processed.

        Raises:
            ValueError: If an embedding vector does not match ``self._dimension``.
        """
        with self._session_factory.begin() as session:
            count = 0
            for chunk_id, vector in items:
                if len(vector) != self._dimension:
                    raise ValueError(
                        "Embedding dimension mismatch: "
                        f"expected {self._dimension}, got {len(vector)}"
                    )
                key = (chunk_id, provider_name, model_name, model_version)
                row = session.get(ChunkEmbeddingRow, key)
                if row is None:
                    session.add(
                        ChunkEmbeddingRow(
                            chunk_id=chunk_id,
                            provider_name=provider_name,
                            model_name=model_name,
                            model_version=model_version,
                            embedding=vector,
                            created_at=utc_now(),
                        )
                    )
                else:
                    row.embedding = vector
                count += 1
        return count

    def search_vector(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        symbol: str | None = None,
        decision_at: datetime | None = None,
        doc_types: tuple[str, ...] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search stored embeddings with metadata and point-in-time filters.

        Computes cosine similarity between ``query_vector`` and every stored
        embedding, then returns the top-k chunks sorted by similarity. Optional
        filters narrow results by symbol, availability timestamp, and document type.

        Args:
            query_vector: Dense query vector to compare against stored embeddings.
            top_k: Maximum number of results to return.
            symbol: Optional ticker/security symbol filter.
            decision_at: Optional point-in-time filter; only chunks with
                ``available_at <= decision_at`` are returned.
            doc_types: Optional tuple of document type values to include.

        Returns:
            A list of ``(Chunk, score)`` tuples sorted by descending similarity.

        Raises:
            ValueError: If ``query_vector`` does not match ``self._dimension``.
        """
        if len(query_vector) != self._dimension:
            raise ValueError(
                f"Query dimension mismatch: expected {self._dimension}, got {len(query_vector)}"
            )
        with self._session_factory() as session:
            statement = select(ChunkRow, ChunkEmbeddingRow).join(
                ChunkEmbeddingRow,
                ChunkEmbeddingRow.chunk_id == ChunkRow.chunk_id,
            )
            if symbol:
                statement = statement.where(ChunkRow.symbol == symbol)
            if decision_at:
                statement = statement.where(ChunkRow.available_at <= decision_at)
            if doc_types:
                statement = statement.where(ChunkRow.doc_type.in_(doc_types))
            rows = session.execute(statement).all()

        scored = [
            (_chunk_from_row(chunk_row), _cosine(query_vector, list(embedding_row.embedding)))
            for chunk_row, embedding_row in rows
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Fetch a chunk by its stable identifier.

        Args:
            chunk_id: Unique chunk identifier.

        Returns:
            The matching ``Chunk`` domain object, or ``None`` if not found.
        """
        with self._session_factory() as session:
            row = session.get(ChunkRow, chunk_id)
            return _chunk_from_row(row) if row is not None else None

    def record_index_audit(
        self,
        *,
        operation: str,
        provider_name: str,
        model_name: str,
        model_version: str,
        chunk_count: int,
        vector_count: int,
        keyword_count: int,
        degraded: bool,
        error: str | None = None,
    ) -> int:
        """Persist an indexing audit record.

        Args:
            operation: Name of the indexing operation performed.
            provider_name: Name of the embedding provider used.
            model_name: Name of the embedding model used.
            model_version: Version of the embedding model used.
            chunk_count: Number of chunks touched.
            vector_count: Number of vectors written.
            keyword_count: Number of keyword entries written.
            degraded: Whether the operation completed in a degraded state.
            error: Optional error message if the operation failed.

        Returns:
            The generated ``audit_id``.
        """
        with self._session_factory.begin() as session:
            row = IndexAuditRecordRow(
                operation=operation,
                provider_name=provider_name,
                model_name=model_name,
                model_version=model_version,
                chunk_count=chunk_count,
                vector_count=vector_count,
                keyword_count=keyword_count,
                degraded=degraded,
                error=error,
                created_at=utc_now(),
            )
            session.add(row)
            session.flush()
            return int(row.audit_id)

    def record_retrieval_audit(
        self,
        *,
        query: str,
        constraints: dict,
        results: list[RetrievalResult],
    ) -> int:
        """Persist replayable retrieval candidates and component scores.

        Args:
            query: Original plain-text query.
            constraints: Query constraints used during retrieval.
            results: List of ``RetrievalResult`` candidates to record.

        Returns:
            The generated ``audit_id``.
        """
        payload = [
            {
                "chunk_id": result.chunk.chunk_id,
                "score": result.score,
                "vector_score": result.vector_score,
                "keyword_score": result.keyword_score,
                "time_decay": result.time_decay,
                "source_quality": result.source_quality,
                "entity_match": result.entity_match,
                "rank": result.rank,
            }
            for result in results
        ]
        result_hash = "sha256:" + hashlib.sha256(
            repr((query, constraints, payload)).encode("utf-8")
        ).hexdigest()
        with self._session_factory.begin() as session:
            row = RetrievalAuditRecordRow(
                query=query,
                constraints=constraints,
                results=payload,
                result_hash=result_hash,
                created_at=utc_now(),
            )
            session.add(row)
            session.flush()
            return int(row.audit_id)

    def replay_retrieval(self, audit_id: int) -> list[RetrievalResult]:
        """Replay a retrieval audit using recorded immutable candidates.

        Reconstructs the original result list by looking up each recorded chunk ID.
        The returned ``RetrievalResult`` objects preserve the component scores that
        were stored at audit time.

        Args:
            audit_id: Primary key of the retrieval audit record.

        Returns:
            The ordered list of ``RetrievalResult`` objects recorded for the audit.

        Raises:
            KeyError: If the audit record is missing or if a referenced chunk cannot
                be found.
        """
        with self._session_factory() as session:
            audit = session.get(RetrievalAuditRecordRow, audit_id)
            if audit is None:
                raise KeyError(f"Retrieval audit '{audit_id}' not found")
            results: list[RetrievalResult] = []
            for item in audit.results:
                chunk = session.get(ChunkRow, item["chunk_id"])
                if chunk is None:
                    raise KeyError(f"Chunk '{item['chunk_id']}' missing for replay")
                results.append(
                    RetrievalResult(
                        chunk=_chunk_from_row(chunk),
                        score=float(item["score"]),
                        vector_score=float(item["vector_score"]),
                        keyword_score=float(item["keyword_score"]),
                        time_decay=float(item["time_decay"]),
                        source_quality=float(item["source_quality"]),
                        entity_match=float(item["entity_match"]),
                        rank=int(item["rank"]),
                    )
                )
            return results


def _chunk_to_row(chunk: Chunk) -> ChunkRow:
    """Convert a ``Chunk`` domain object into a new ``ChunkRow``.

    Args:
        chunk: The domain object to convert.

    Returns:
        A populated ``ChunkRow`` instance.
    """
    return ChunkRow(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        content=chunk.content,
        content_hash=chunk.content_hash,
        symbol=chunk.symbol,
        source_level=int(chunk.source_level),
        doc_type=chunk.doc_type.value,
        published_at=chunk.published_at,
        available_at=chunk.available_at,
        source_url=chunk.source_url,
        source_name=chunk.source_name,
        snapshot_id=chunk.snapshot_id,
        snapshot_hash=chunk.snapshot_hash,
        page=chunk.page,
        section=chunk.section,
        paragraph_index=chunk.paragraph_index,
        table_id=chunk.table_id,
        row_id=chunk.row_id,
        quote_span=list(chunk.quote_span) if chunk.quote_span else None,
        keywords=list(chunk.keywords),
        chunk_index=chunk.chunk_index,
        total_chunks=chunk.total_chunks,
    )


def _update_chunk_row(row: ChunkRow, chunk: Chunk) -> None:
    """Update an existing ``ChunkRow`` in place from a ``Chunk`` domain object.

    All columns except the primary key ``chunk_id`` are overwritten.

    Args:
        row: The existing database row to update.
        chunk: The domain object containing the latest values.
    """
    new = _chunk_to_row(chunk)
    for column in ChunkRow.__table__.columns:
        if column.name != "chunk_id":
            setattr(row, column.name, getattr(new, column.name))


def _chunk_from_row(row: ChunkRow) -> Chunk:
    """Convert a ``ChunkRow`` into a ``Chunk`` domain object.

    Args:
        row: The database row to convert.

    Returns:
        A frozen ``Chunk`` instance reconstructed from the row.
    """
    return Chunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        content=row.content,
        content_hash=row.content_hash,
        symbol=row.symbol,
        source_level=SourceLevel(row.source_level),
        doc_type=DocType(row.doc_type),
        published_at=row.published_at,
        available_at=row.available_at,
        source_url=row.source_url,
        source_name=row.source_name,
        snapshot_id=row.snapshot_id,
        snapshot_hash=row.snapshot_hash,
        page=row.page,
        section=row.section,
        paragraph_index=row.paragraph_index,
        table_id=row.table_id,
        row_id=row.row_id,
        quote_span=tuple(row.quote_span) if row.quote_span else None,
        keywords=tuple(row.keywords),
        chunk_index=row.chunk_index,
        total_chunks=row.total_chunks,
    )


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in the range [-1.0, 1.0], or ``0.0`` if either
        vector has zero norm.

    Raises:
        ValueError: If the input vectors have different lengths. The error is
            raised by ``zip(..., strict=True)``.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
