"""v0.2 PIT retrieval through chunk-security links.

Verifies that ``HybridRetriever`` filters future chunks at the SQL level using
``available_at`` constraints and that retrieval results carry locator snapshots
and source-quality scores for citation support.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from margin.news.models import SourceLevel
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.db_models import ChunkEmbeddingRow, ChunkRow, ChunkSecurityLinkRow
from margin.vector.models import (
    ChunkSecurityLink,
    DocType,
    SourceLocator,
    TrustLevel,
    make_chunk,
)
from margin.vector.repository import VectorRepository
from margin.vector.retrieval import HybridRetriever


@pytest.fixture
def vector_repository(database_url: str) -> Iterator[VectorRepository]:
    """Yield a clean ``VectorRepository`` backed by a temporary PostgreSQL database.

    Args:
        database_url: str: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (ChunkSecurityLinkRow, ChunkEmbeddingRow, ChunkRow):
            session.query(row).delete()
    repo = VectorRepository(session_factory, dimension=2)
    yield repo
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeEmbeddingProvider:
    """Stub embedding provider returning a fixed 2-D vector for any input.."""

    def embed(self, text: str) -> list[float]:
        """Return a constant ``[1.0, 0.0]`` vector, ignoring the input text.

        Args:
            text: str: .

        Returns:
            list[float]: .
        """
        return [1.0, 0.0]


def seed_chunk(
    repo: VectorRepository,
    *,
    chunk_id: str,
    security_id: str,
    available_at: datetime,
    content: str = "收入增长",
) -> None:
    """Insert a chunk with a security link and embedding into the repository.

    Args:
        repo: VectorRepository: .
        chunk_id: str: .
        security_id: str: .
        available_at: datetime: .
        content: str: .

    Returns:
        None: .
    """
    chunk = make_chunk(
        document_id=f"doc-{chunk_id}",
        content=content,
        source_level=SourceLevel.L1,
        doc_type=DocType.NEWS,
        available_at=available_at,
        published_at=available_at,
        source_url="https://example.com/a",
        snapshot_id=f"snp-{chunk_id}",
        snapshot_hash="sha256:snapshot",
        locator=SourceLocator(page=1, quote_span=(0, len(content))),
        trust_level=TrustLevel.TRUSTED_OFFICIAL_CONTENT,
    ).model_copy(update={"chunk_id": chunk_id})
    repo.upsert_chunks(
        [chunk],
        links=[
            ChunkSecurityLink(
                chunk_id=chunk_id,
                security_id=security_id,
                link_type="mentioned",
                confidence=1.0,
            )
        ],
    )
    repo.upsert_embeddings(
        [(chunk_id, [1.0, 0.0])],
        provider_name="fake",
        model_name="fake",
        model_version="v1",
    )


def test_retrieval_filters_future_chunks_in_sql(
    vector_repository: VectorRepository,
) -> None:
    """Retrieval must filter out chunks whose ``available_at`` is after the decision time.

    Args:
        vector_repository: VectorRepository: .

    Returns:
        None: .
    """
    seed_chunk(
        vector_repository,
        chunk_id="past",
        security_id="000001.SZ",
        available_at=datetime(2026, 6, 21, tzinfo=UTC),
    )
    seed_chunk(
        vector_repository,
        chunk_id="future",
        security_id="000001.SZ",
        available_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    retriever = HybridRetriever(
        vector_repository,
        embedding_provider=FakeEmbeddingProvider(),
    )

    results = retriever.search(
        query="收入增长",
        security_ids=("000001.SZ",),
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        top_k=10,
    )

    assert [result.chunk.chunk_id for result in results] == ["past"]


def test_retrieval_returns_locator_snapshot_and_quality(
    vector_repository: VectorRepository,
) -> None:
    """Retrieval results must carry locator snapshots and positive source-quality scores.

    Args:
        vector_repository: VectorRepository: .

    Returns:
        None: .
    """
    seed_chunk(
        vector_repository,
        chunk_id="penalty",
        security_id="000001.SZ",
        available_at=datetime(2026, 6, 21, tzinfo=UTC),
        content="监管处罚",
    )
    retriever = HybridRetriever(
        vector_repository,
        embedding_provider=FakeEmbeddingProvider(),
    )

    [result] = retriever.search(
        query="监管处罚",
        security_ids=("000001.SZ",),
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        top_k=1,
    )

    assert result.chunk.snapshot_id
    assert result.chunk.locator.has_precise_anchor
    assert result.source_quality > 0
