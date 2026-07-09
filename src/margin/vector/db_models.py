"""SQLAlchemy table definitions for chunk, embedding, and retrieval audit persistence.

This module contains the declarative ORM models that map chunks, per-model
dense embeddings, indexing audit records, and retrieval audit records to the
underlying PostgreSQL tables used by the vector search pipeline.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ChunkRow(Base):
    """Persisted immutable chunk metadata.."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_symbol_available", "symbol", "available_at"),
        Index("ix_chunks_doc_type", "doc_type"),
        Index("ix_chunks_active_available", "is_active", "available_at"),
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
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trust_level: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="trusted_official_content",
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)


class ChunkSecurityLinkRow(Base):
    """Many-to-many security relation for a chunk.."""

    __tablename__ = "chunk_security_links"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "security_id",
            "link_type",
            name="uq_chunk_security_link",
        ),
        Index("ix_chunk_security_links_security", "security_id", "chunk_id"),
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"),
        primary_key=True,
    )
    security_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    link_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class IndexedDocumentRow(Base):
    """Audit row for a parsed/chunked/indexed document.."""

    __tablename__ = "indexed_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    embedding_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChunkEmbeddingRow(Base):
    """Model-versioned dense vector embedding for a chunk.."""

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
    """Persistent indexing audit record.."""

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
    """Persistent retrieval audit and replay record.."""

    __tablename__ = "retrieval_audit_records"

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
