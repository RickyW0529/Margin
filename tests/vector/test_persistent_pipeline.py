"""Tests for PostgreSQL-backed retrieval pipeline adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline


class FakeEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


class FakeVectorRepository:
    def __init__(self, chunk) -> None:
        self.chunk = chunk

    def search_vector(self, query_vector, **kwargs):
        del query_vector, kwargs
        return [(self.chunk, 0.9)]

    def list_chunks(self, **kwargs):
        del kwargs
        return [self.chunk]


def test_persistent_pipeline_combines_database_vector_and_keyword_results():
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
