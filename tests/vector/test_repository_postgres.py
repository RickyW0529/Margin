"""Tests for the PostgreSQL/pgvector vector repository.

Covers chunk persistence, embedding upserts, filtered vector search by symbol and
availability window, retrieval audit logging, and replay of audited retrievals.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from margin.news.models import SourceLevel
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.db_models import (
    ChunkEmbeddingRow,
    ChunkRow,
    IndexAuditRecordRow,
    RetrievalAuditRecordRow,
)
from margin.vector.models import DocType, RetrievalResult, make_chunk
from margin.vector.repository import VectorRepository


@pytest.fixture
def vector_repository(database_url):
    """Yield a clean ``VectorRepository`` backed by a temporary PostgreSQL database.

    Args:
        database_url: pytest fixture providing the connection URL for the test database.

    Yields:
        VectorRepository: repository instance with dimension 3 and empty vector tables.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            RetrievalAuditRecordRow,
            IndexAuditRecordRow,
            ChunkEmbeddingRow,
            ChunkRow,
        ):
            session.query(row).delete()
    yield VectorRepository(session_factory, dimension=3)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _chunk(chunk_id: str, symbol: str, available_at: datetime):
    """Build a minimal ``Chunk`` for repository tests.

    Args:
        chunk_id: identifier assigned to the generated chunk.
        symbol: stock symbol stored on the chunk.
        available_at: timestamp controlling search availability.

    Returns:
        Chunk: a filing chunk with the requested overrides.
    """
    chunk = make_chunk(
        document_id=f"doc_{chunk_id}",
        content=f"{symbol} 经营现金流改善",
        symbol=symbol,
        source_level=SourceLevel.L1,
        doc_type=DocType.FILING,
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        available_at=available_at,
        source_url="https://example.com/a",
        page=1,
    )
    return chunk.model_copy(update={"chunk_id": chunk_id})


def test_vector_repository_upserts_chunks_vectors_filters_and_replays(vector_repository):
    """End-to-end repository flow must persist and retrieve chunks correctly.

    Verifies that:
      - upserting chunks stores them,
      - upserting embeddings stores 3-D vectors,
      - vector search filters by symbol and decision time,
      - retrieval audit records are persisted,
      - replaying an audit returns the same result.
    """
    early = _chunk("chk_early", "000001.SZ", datetime(2026, 6, 1, tzinfo=UTC))
    late = _chunk("chk_late", "000001.SZ", datetime(2026, 7, 1, tzinfo=UTC))
    other = _chunk("chk_other", "600000.SH", datetime(2026, 6, 1, tzinfo=UTC))
    vector_repository.upsert_chunks([early, late, other])
    vector_repository.upsert_embeddings(
        [
            (early.chunk_id, [1.0, 0.0, 0.0]),
            (late.chunk_id, [0.9, 0.1, 0.0]),
            (other.chunk_id, [1.0, 0.0, 0.0]),
        ],
        provider_name="test",
        model_name="demo",
        model_version="v1",
    )

    results = vector_repository.search_vector(
        [1.0, 0.0, 0.0],
        top_k=5,
        symbol="000001.SZ",
        decision_at=datetime(2026, 6, 18, tzinfo=UTC),
    )

    assert [chunk.chunk_id for chunk, _ in results] == [early.chunk_id]

    audit_id = vector_repository.record_retrieval_audit(
        query="现金流",
        constraints={"symbol": "000001.SZ"},
        results=[
            RetrievalResult(
                chunk=early,
                score=0.9,
                vector_score=0.8,
                keyword_score=0.1,
                rank=1,
            )
        ],
    )

    replayed = vector_repository.replay_retrieval(audit_id)
    assert replayed[0].chunk.chunk_id == early.chunk_id
    assert replayed[0].score == 0.9
