"""Vector index and retrieval query factory."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select

from margin.vector.db_models import (
    ChunkEmbeddingRow,
    ChunkRow,
    ChunkSecurityLinkRow,
)


def count_chunk_security_links() -> Select:
    """Return a count query for all chunk-security link rows."""
    return select(func.count()).select_from(ChunkSecurityLinkRow)


def chunk_security_link_count(
    chunk_id: str,
    security_id: str,
) -> Select:
    """Return a count query for a specific chunk-security link."""
    return (
        select(func.count())
        .select_from(ChunkSecurityLinkRow)
        .where(
            ChunkSecurityLinkRow.chunk_id == chunk_id,
            ChunkSecurityLinkRow.security_id == security_id,
        )
    )


def count_embeddings() -> Select:
    """Return a count query for all embedding rows."""
    return select(func.count()).select_from(ChunkEmbeddingRow)


def search_vector_statement(
    *,
    security_ids: tuple[str, ...] | None = None,
    symbol: str | None = None,
    decision_at: datetime | None = None,
    doc_types: tuple[str, ...] | None = None,
) -> Select:
    """Return a chunk-embedding join statement with metadata and PIT filters."""
    statement = select(ChunkRow, ChunkEmbeddingRow).join(
        ChunkEmbeddingRow,
        ChunkEmbeddingRow.chunk_id == ChunkRow.chunk_id,
    )
    statement = statement.where(ChunkRow.is_active.is_(True))
    if security_ids:
        statement = statement.join(
            ChunkSecurityLinkRow,
            ChunkSecurityLinkRow.chunk_id == ChunkRow.chunk_id,
        ).where(ChunkSecurityLinkRow.security_id.in_(security_ids))
    elif symbol:
        statement = statement.where(ChunkRow.symbol == symbol)
    if decision_at:
        statement = statement.where(ChunkRow.available_at <= decision_at)
    if doc_types:
        statement = statement.where(ChunkRow.doc_type.in_(doc_types))
    return statement


def list_chunks_statement(
    *,
    symbol: str | None = None,
    security_ids: tuple[str, ...] | None = None,
    doc_types: tuple[str, ...] | None = None,
    decision_at: datetime | None = None,
) -> Select:
    """Return a chunk select statement with optional filters and ordering."""
    statement = select(ChunkRow)
    statement = statement.where(ChunkRow.is_active.is_(True))
    if security_ids:
        statement = statement.join(
            ChunkSecurityLinkRow,
            ChunkSecurityLinkRow.chunk_id == ChunkRow.chunk_id,
        ).where(ChunkSecurityLinkRow.security_id.in_(security_ids))
    elif symbol:
        statement = statement.where(ChunkRow.symbol == symbol)
    if decision_at:
        statement = statement.where(ChunkRow.available_at <= decision_at)
    if doc_types:
        statement = statement.where(ChunkRow.doc_type.in_(doc_types))
    return statement.order_by(
        ChunkRow.available_at.desc(),
        ChunkRow.chunk_id,
    )
