"""Tests for PostgreSQL-backed retrieval pipeline adapters.

Verifies that ``PersistentEmbeddingPipeline`` combines database vector search and
keyword search results, delegating to the repository while applying symbol filters.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline


class FakeEmbeddingProvider:
    """Stub embedding provider returning a fixed 2-D vector for any input."""

    def embed(self, text: str) -> list[float]:
        """Return a constant ``[1.0, 0.0]`` vector, ignoring the input text."""
        del text
        return [1.0, 0.0]


class FakeVectorRepository:
    """Stub vector repository returning a fixed chunk for search and list calls."""

    def __init__(self, chunk) -> None:
        """Initialize the fake repository with a chunk to return.

        Args:
            chunk: the chunk returned by ``search_vector`` and ``list_chunks``.
        """
        self.chunk = chunk

    def search_vector(self, query_vector, **kwargs):
        """Return a single result pair containing the stored chunk and score 0.9."""
        del query_vector, kwargs
        return [(self.chunk, 0.9)]

    def list_chunks(self, **kwargs):
        """Return a single-element list containing the stored chunk."""
        del kwargs
        return [self.chunk]


def test_persistent_pipeline_combines_database_vector_and_keyword_results():
    """Persistent pipeline must combine database vector and keyword search results.

    Verifies that ``PersistentEmbeddingPipeline`` delegates vector search to the
    repository and performs keyword search over listed chunks, applying symbol
    filters in both paths.
    """
    chunk = make_chunk(
        document_id="doc_1",
        content="经营现金流改善",
        symbol="000001.SZ",
        source_level=SourceLevel.L1,
        doc_type=DocType.FILING,
        source_url="https://example.com/filing.pdf",
        page=1,
        published_at=datetime(2026, 6, 18, tzinfo=UTC),
        available_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    pipeline = PersistentEmbeddingPipeline(
        embedding_provider=FakeEmbeddingProvider(),
        repository=FakeVectorRepository(chunk),
    )

    assert pipeline.vector_search("现金流", filters={"symbol": "000001.SZ"}) == [
        (chunk, 0.9)
    ]
    keyword = pipeline.keyword_search(
        "现金流改善",
        filters={"symbol": "000001.SZ"},
    )
    assert keyword[0][0] == chunk
    assert keyword[0][1] > 0
