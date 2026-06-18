"""SQLAlchemy table definitions for chunk, embedding, and retrieval audit persistence.

This module contains the declarative ORM models that map chunks, per-model
dense embeddings, indexing audit records, and retrieval audit records to the
underlying PostgreSQL tables used by the vector search pipeline.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ChunkRow(Base):
    """Persisted immutable chunk metadata.

    A ``ChunkRow`` stores the content, provenance, and structural locators for a
    single document chunk. It is the authoritative source for chunk metadata and
    is referenced by ``ChunkEmbeddingRow``.

    Attributes:
        chunk_id: Stable primary key of the chunk.
        document_id: Identifier of the parent document.
        content: Plain-text chunk content.
        content_hash: Hash of the content used for integrity checks.
        symbol: Optional ticker/security symbol associated with the source.
        source_level: Numeric source reliability level.
        doc_type: Document category (e.g. ``annual_report``, ``news``).
        published_at: Original publication timestamp in UTC.
        available_at: Timestamp when the content became available in UTC.
        source_url: Optional URL to the original source.
        source_name: Optional human-readable source name.
        snapshot_id: Optional identifier of the captured web snapshot.
        snapshot_hash: Optional hash of the captured snapshot.
        page: Optional page number in the source document.
        section: Optional section or chapter name.
        paragraph_index: Optional paragraph sequence number.
        table_id: Optional table identifier.
        row_id: Optional table row identifier.
        quote_span: Optional [start, end] character span stored as JSONB.
        keywords: List of extracted keyword/BM25 terms stored as JSONB.
        chunk_index: Zero-based position of this chunk within the document.
        total_chunks: Total number of chunks produced for the document.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_symbol_available", "symbol", "available_at"),
        Index("ix_chunks_doc_type", "doc_type"),
    )

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    source_level: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(128))
    snapshot_id: Mapped[str | None] = mapped_column(String(64))
    snapshot_hash: Mapped[str | None] = mapped_column(String(96))
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    table_id: Mapped[str | None] = mapped_column(String(64))
    row_id: Mapped[str | None] = mapped_column(String(64))
    quote_span: Mapped[list[int] | None] = mapped_column(JSONB)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)


class ChunkEmbeddingRow(Base):
    """Model-versioned dense vector embedding for a chunk.

    Each row links a ``ChunkRow`` to an embedding produced by a specific provider,
    model, and model version. The combination of ``chunk_id``, ``provider_name``,
    ``model_name``, and ``model_version`` forms the composite primary key.

    Attributes:
        chunk_id: Foreign key referencing ``chunks.chunk_id``.
        provider_name: Name of the embedding provider.
        model_name: Name of the embedding model.
        model_version: Version of the embedding model.
        embedding: Dense vector stored as a pgvector ``Vector``.
        created_at: Timestamp when the embedding was persisted in UTC.
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IndexAuditRecordRow(Base):
    """Persistent indexing audit record.

    Captures the outcome of an indexing operation, including counts of chunks,
    vectors, and keyword entries, as well as whether the operation degraded or
    failed.

    Attributes:
        audit_id: Auto-incrementing primary key.
        operation: Operation name (e.g. ``index``, ``reindex``).
        provider_name: Name of the embedding provider used.
        model_name: Name of the embedding model used.
        model_version: Version of the embedding model used.
        chunk_count: Number of chunks touched by the operation.
        vector_count: Number of vectors written by the operation.
        keyword_count: Number of keyword entries written by the operation.
        degraded: Whether the operation completed in a degraded state.
        error: Optional error message if the operation failed.
        created_at: Timestamp when the audit record was created in UTC.
    """

    __tablename__ = "index_audit_records"

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False)
    keyword_count: Mapped[int] = mapped_column(Integer, nullable=False)
    degraded: Mapped[bool] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RetrievalAuditRecordRow(Base):
    """Persistent retrieval audit and replay record.

    Stores the query, constraints, and scored candidate list produced by a
    retrieval operation. The recorded data can be replayed later to reconstruct
    the exact result set for evaluation or debugging.

    Attributes:
        audit_id: Auto-incrementing primary key.
        query: Original plain-text query.
        constraints: Query constraints such as symbol or doc type, stored as JSONB.
        results: Ordered list of scored retrieval candidates, stored as JSONB.
        result_hash: SHA-256 hash of the query, constraints, and results.
        created_at: Timestamp when the retrieval was recorded in UTC.
    """

    __tablename__ = "retrieval_audit_records"

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
