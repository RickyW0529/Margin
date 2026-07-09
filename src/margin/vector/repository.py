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

from sqlalchemy.orm import Session

from margin.news.models import SourceLevel, utc_now
from margin.sql.vector_queries import (
    chunk_security_link_count,
    count_chunk_security_links,
    count_embeddings,
    list_chunks_statement,
    search_vector_statement,
)
from margin.vector.db_models import (
    ChunkEmbeddingRow,
    ChunkRow,
    ChunkSecurityLinkRow,
    IndexAuditRecordRow,
    IndexedDocumentRow,
    RetrievalAuditRecordRow,
)
from margin.vector.models import (
    Chunk,
    ChunkSecurityLink,
    DocType,
    IndexedDocument,
    RetrievalResult,
    SourceLocator,
    TrustLevel,
)


class VectorRepository:
    """Persistent chunk/vector/audit boundary.."""

    def __init__(self, session_factory: Callable[[], Session], *, dimension: int) -> None:
        """Initialize a new repository instance.

        Args:
            session_factory: Callable[[], Session]: .
            dimension: int: .

        Returns:
            None: .
        """
        self._session_factory = session_factory
        self._dimension = dimension

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        *,
        links: list[ChunkSecurityLink] | None = None,
    ) -> int:
        """Persist chunk metadata idempotently.

        Args:
            chunks: list[Chunk]: .
            links: list[ChunkSecurityLink] | None: .

        Returns:
            int: .
        """
        with self._session_factory.begin() as session:
            for chunk in chunks:
                row = session.get(ChunkRow, chunk.chunk_id)
                if row is None:
                    session.add(_chunk_to_row(chunk))
                else:
                    _update_chunk_row(row, chunk)
            for link in links or []:
                key = (link.chunk_id, link.security_id, link.link_type)
                row = session.get(ChunkSecurityLinkRow, key)
                if row is None:
                    session.add(
                        ChunkSecurityLinkRow(
                            chunk_id=link.chunk_id,
                            security_id=link.security_id,
                            link_type=link.link_type,
                            confidence=link.confidence,
                        )
                    )
                else:
                    row.confidence = link.confidence
        return len(chunks)

    def count_chunk_security_links(self) -> int:
        """Return persisted chunk-security link count.

        Returns:
            int: .
        """
        with self._session_factory() as session:
            return int(session.scalar(count_chunk_security_links()) or 0)

    def chunk_has_security_link(self, chunk_id: str, security_id: str) -> bool:
        """Return whether a chunk is linked to a security through v0.2 links.

        Args:
            chunk_id: str: .
            security_id: str: .

        Returns:
            bool: .
        """
        with self._session_factory() as session:
            return (session.scalar(chunk_security_link_count(chunk_id, security_id)) or 0) > 0

    def count_embeddings(self) -> int:
        """Return persisted embedding row count.

        Returns:
            int: .
        """
        with self._session_factory() as session:
            return int(session.scalar(count_embeddings()) or 0)

    def upsert_indexed_document(self, document: IndexedDocument) -> None:
        """Persist parser/chunker/indexing audit for a document.

        Args:
            document: IndexedDocument: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(IndexedDocumentRow, document.document_id)
            if row is None:
                session.add(
                    IndexedDocumentRow(
                        document_id=document.document_id,
                        event_id=document.event_id,
                        parser_version=document.parser_version,
                        input_hash=document.input_hash,
                        chunk_ids=list(document.chunk_ids),
                        embedding_keys=list(document.embedding_keys),
                        created_at=document.created_at,
                    )
                )
            else:
                row.event_id = document.event_id
                row.parser_version = document.parser_version
                row.input_hash = document.input_hash
                row.chunk_ids = list(document.chunk_ids)
                row.embedding_keys = list(document.embedding_keys)

    def get_indexed_document(self, document_id: str) -> IndexedDocument | None:
        """Fetch indexed document audit by document id.

        Args:
            document_id: str: .

        Returns:
            IndexedDocument | None: .
        """
        with self._session_factory() as session:
            row = session.get(IndexedDocumentRow, document_id)
            if row is None:
                return None
            return IndexedDocument(
                document_id=row.document_id,
                event_id=row.event_id,
                parser_version=row.parser_version,
                input_hash=row.input_hash,
                chunk_ids=tuple(row.chunk_ids),
                embedding_keys=tuple(row.embedding_keys),
                created_at=row.created_at,
            )

    def upsert_embeddings(
        self,
        items: list[tuple[str, list[float]]],
        *,
        provider_name: str,
        model_name: str,
        model_version: str,
    ) -> int:
        """Persist model-versioned embeddings idempotently.

        Args:
            items: list[tuple[str, list[float]]]: .
            provider_name: str: .
            model_name: str: .
            model_version: str: .

        Returns:
            int: .
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
        security_ids: tuple[str, ...] | None = None,
        decision_at: datetime | None = None,
        doc_types: tuple[str, ...] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search stored embeddings with metadata and point-in-time filters.

        Args:
            query_vector: list[float]: .
            top_k: int: .
            symbol: str | None: .
            security_ids: tuple[str, ...] | None: .
            decision_at: datetime | None: .
            doc_types: tuple[str, ...] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
        """
        if len(query_vector) != self._dimension:
            raise ValueError(
                f"Query dimension mismatch: expected {self._dimension}, got {len(query_vector)}"
            )
        with self._session_factory() as session:
            statement = search_vector_statement(
                security_ids=security_ids,
                symbol=symbol,
                decision_at=decision_at,
                doc_types=doc_types,
            )
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
            chunk_id: str: .

        Returns:
            Chunk | None: .
        """
        with self._session_factory() as session:
            row = session.get(ChunkRow, chunk_id)
            return _chunk_from_row(row) if row is not None else None

    def list_chunks(
        self,
        *,
        symbol: str | None = None,
        security_ids: tuple[str, ...] | None = None,
        doc_types: tuple[str, ...] | None = None,
        decision_at: datetime | None = None,
    ) -> list[Chunk]:
        """Return persisted chunks for keyword fallback retrieval.

        Args:
            symbol: str | None: .
            security_ids: tuple[str, ...] | None: .
            doc_types: tuple[str, ...] | None: .
            decision_at: datetime | None: .

        Returns:
            list[Chunk]: .
        """
        statement = list_chunks_statement(
            symbol=symbol,
            security_ids=security_ids,
            doc_types=doc_types,
            decision_at=decision_at,
        )
        with self._session_factory() as session:
            return [_chunk_from_row(row) for row in session.scalars(statement).all()]

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
            operation: str: .
            provider_name: str: .
            model_name: str: .
            model_version: str: .
            chunk_count: int: .
            vector_count: int: .
            keyword_count: int: .
            degraded: bool: .
            error: str | None: .

        Returns:
            int: .
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
            query: str: .
            constraints: dict: .
            results: list[RetrievalResult]: .

        Returns:
            int: .
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
        result_hash = (
            "sha256:"
            + hashlib.sha256(repr((query, constraints, payload)).encode("utf-8")).hexdigest()
        )
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

        Args:
            audit_id: int: .

        Returns:
            list[RetrievalResult]: .
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
        chunk: Chunk: .

    Returns:
        ChunkRow: .
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
        locator=chunk.locator.model_dump(mode="json", exclude_none=True),
        trust_level=chunk.trust_level.value,
        is_active=chunk.is_active,
        keywords=list(chunk.keywords),
        chunk_index=chunk.chunk_index,
        total_chunks=chunk.total_chunks,
    )


def _update_chunk_row(row: ChunkRow, chunk: Chunk) -> None:
    """Update an existing ``ChunkRow`` in place from a ``Chunk`` domain object.

    Args:
        row: ChunkRow: .
        chunk: Chunk: .

    Returns:
        None: .
    """
    new = _chunk_to_row(chunk)
    for column in ChunkRow.__table__.columns:
        if column.name != "chunk_id":
            setattr(row, column.name, getattr(new, column.name))


def _chunk_from_row(row: ChunkRow) -> Chunk:
    """Convert a ``ChunkRow`` into a ``Chunk`` domain object.

    Args:
        row: ChunkRow: .

    Returns:
        Chunk: .
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
        locator=SourceLocator(**(row.locator or {})),
        trust_level=TrustLevel(row.trust_level),
        is_active=row.is_active,
        keywords=tuple(row.keywords),
        chunk_index=row.chunk_index,
        total_chunks=row.total_chunks,
    )


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors.

    Args:
        a: list[float]: .
        b: list[float]: .

    Returns:
        float: .
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
