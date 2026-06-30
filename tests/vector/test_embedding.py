"""Tests for embeddings, vector store, BM25 keyword index, and the indexing pipeline.

Covers ``EmbeddingProvider`` hashing/normalization, ``VectorStore`` upsert/search,
``BM25Index`` keyword ranking, ``EmbeddingPipeline`` combined indexing with graceful
degradation, and an end-to-end chunking-to-indexing flow from a document event.
"""

from __future__ import annotations

import pytest

from margin.core.provider import ProviderType
from margin.core.registry import ProviderRegistry
from margin.news.models import SourceLevel, make_document_event
from margin.vector.chunker import Chunker
from margin.vector.embedding import (
    BM25Index,
    EmbeddingPipeline,
    EmbeddingProvider,
    VectorStore,
)
from margin.vector.models import make_chunk


def _make_chunks(n=3, prefix="test"):
    """Create a list of test chunks.

    Args:
        n: Number of chunks to create.
        prefix: Text prefix placed in each chunk's content.

    Returns:
        A list of ``Chunk`` objects ready for indexing.
    """
    return [
        make_chunk(
            document_id="doc_1",
            content=f"{prefix} content {i} with keyword",
            chunk_index=i,
            total_chunks=n,
            symbol="000001.SZ",
            source_level=SourceLevel.L1,
        )
        for i in range(n)
    ]


class TestEmbeddingProvider:
    """Tests for ``EmbeddingProvider`` including hashing, normalization, and registry contract."""

    def test_hash_embed_deterministic(self):
        """Verify embedding the same text twice yields identical vectors."""
        provider = EmbeddingProvider(dim=64)
        v1 = provider.embed("hello world")
        v2 = provider.embed("hello world")
        assert v1 == v2

    def test_different_text_different_vector(self):
        """Verify different texts produce different vectors."""
        provider = EmbeddingProvider(dim=64)
        v1 = provider.embed("hello")
        v2 = provider.embed("world")
        assert v1 != v2

    def test_dim_correct(self):
        """Verify the returned vector dimension matches the configured ``dim``."""
        provider = EmbeddingProvider(dim=128)
        vec = provider.embed("test")
        assert len(vec) == 128

    def test_normalized(self):
        """Verify output vectors are L2-normalized."""
        import math

        provider = EmbeddingProvider(dim=64)
        vec = provider.embed("some text")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 0.01

    def test_batch_embed(self):
        """Verify ``embed_batch`` returns one vector per input text."""
        provider = EmbeddingProvider(dim=32)
        texts = ["a", "b", "c"]
        vectors = provider.embed_batch(texts)
        assert len(vectors) == 3
        assert all(len(v) == 32 for v in vectors)

    def test_custom_embed_func(self):
        """Verify a custom embedding function overrides the default behavior."""
        def custom(text):
            """custom."""
            return [0.1] * 16

        provider = EmbeddingProvider(dim=16, embed_func=custom)
        vec = provider.embed("test")
        assert vec == [0.1] * 16

    def test_provider_registry_contract(self):
        """Verify the provider can be registered and retrieved via ``ProviderRegistry``."""
        provider = EmbeddingProvider(dim=16)
        registry = ProviderRegistry()

        registry.register(provider)

        assert registry.get(provider.descriptor.name) is provider
        assert provider.descriptor.provider_type == ProviderType.EMBEDDING
        assert provider.healthcheck().status.value == "healthy"


class TestVectorStore:
    """Tests for ``VectorStore`` upsert/search/filter/clear behavior."""

    def test_upsert_and_search(self):
        """Verify a single chunk can be upserted and retrieved by vector search."""
        store = VectorStore(dim=64)
        provider = EmbeddingProvider(dim=64)

        chunk = make_chunk(document_id="d1", content="hello world")
        vec = provider.embed("hello world")
        store.upsert(chunk, vec)

        results = store.search(vec, top_k=5)
        assert len(results) == 1
        assert results[0][0].chunk_id == chunk.chunk_id
        assert results[0][1] > 0.99

    def test_dim_mismatch_raises(self):
        """Verify upserting a vector with the wrong dimension raises ``ValueError``."""
        store = VectorStore(dim=64)
        chunk = make_chunk(document_id="d1", content="test")
        with pytest.raises(ValueError, match="dim mismatch"):
            store.upsert(chunk, [0.0] * 32)

    def test_filter_by_symbol(self):
        """Verify vector search can filter results by stock symbol."""
        store = VectorStore(dim=64)
        provider = EmbeddingProvider(dim=64)

        c1 = make_chunk(document_id="d1", content="a", symbol="000001.SZ")
        c2 = make_chunk(document_id="d2", content="b", symbol="600000.SH")
        store.upsert(c1, provider.embed("a"))
        store.upsert(c2, provider.embed("b"))

        results = store.search(
            provider.embed("query"), top_k=5, filters={"symbol": "000001.SZ"}
        )
        assert len(results) == 1
        assert results[0][0].symbol == "000001.SZ"

    def test_batch_upsert(self):
        """Verify ``upsert_batch`` indexes multiple chunks and updates ``size``."""
        store = VectorStore(dim=32)
        provider = EmbeddingProvider(dim=32)

        chunks = _make_chunks(3)
        vectors = [provider.embed(c.content) for c in chunks]
        count = store.upsert_batch(list(zip(chunks, vectors, strict=True)))
        assert count == 3
        assert store.size == 3

    def test_clear(self):
        """Verify ``clear`` removes all entries from the store."""
        store = VectorStore(dim=32)
        provider = EmbeddingProvider(dim=32)
        chunk = make_chunk(document_id="d1", content="test")
        store.upsert(chunk, provider.embed("test"))
        store.clear()
        assert store.size == 0


class TestBM25Index:
    """Tests for ``BM25Index`` keyword search and filter behavior."""

    def test_upsert_and_search(self):
        """Verify BM25 ranks matching Chinese documents above others."""
        index = BM25Index()
        chunks = [
            make_chunk(document_id="d1", content="公司经营现金流改善"),
            make_chunk(document_id="d2", content="公司净利润下降"),
            make_chunk(document_id="d3", content="行业景气度回升"),
        ]
        index.upsert_batch(chunks)

        results = index.search("现金流", top_k=3)
        assert len(results) > 0
        assert results[0][0].content == "公司经营现金流改善"

    def test_search_no_match(self):
        """Verify searching for a term absent from the index returns no results."""
        index = BM25Index()
        index.upsert(make_chunk(document_id="d1", content="hello"))
        results = index.search("nonexistent")
        assert len(results) == 0

    def test_filter_by_symbol(self):
        """Verify BM25 search can filter results by stock symbol."""
        index = BM25Index()
        c1 = make_chunk(document_id="d1", content="现金流", symbol="000001.SZ")
        c2 = make_chunk(document_id="d2", content="现金流", symbol="600000.SH")
        index.upsert(c1)
        index.upsert(c2)

        results = index.search("现金流", top_k=5, filters={"symbol": "000001.SZ"})
        assert len(results) == 1
        assert results[0][0].symbol == "000001.SZ"

    def test_clear(self):
        """Verify ``clear`` removes all entries from the BM25 index."""
        index = BM25Index()
        index.upsert(make_chunk(document_id="d1", content="test"))
        index.clear()
        assert index.size == 0

    def test_reupsert_replaces_document_frequency_contribution(self):
        """Verify re-upserting the same chunk does not inflate document frequency."""
        index = BM25Index()
        chunk = make_chunk(document_id="d1", content="现金流")

        index.upsert(chunk)
        index.upsert(chunk)

        assert len(index.search("现金流")) == 1


class TestEmbeddingPipeline:
    """Tests for ``EmbeddingPipeline`` combining vector and keyword indexing."""

    def test_index_and_search(self):
        """Verify chunks are indexed and searchable by both vector and keyword paths."""
        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )

        chunks = _make_chunks(3, prefix="现金流")
        count = pipeline.index_chunks(chunks)
        assert count == 3

        vector_results = pipeline.vector_search("现金流", top_k=5)
        assert len(vector_results) > 0

        keyword_results = pipeline.keyword_search("现金流", top_k=5)
        assert len(keyword_results) > 0

    def test_index_empty(self):
        """Verify indexing an empty chunk list returns zero and does not fail."""
        pipeline = EmbeddingPipeline()
        count = pipeline.index_chunks([])
        assert count == 0

    def test_audit_logged(self):
        """Verify indexing and searching produce audit records."""
        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=32),
        )
        chunks = _make_chunks(2)
        pipeline.index_chunks(chunks)
        pipeline.vector_search("test", top_k=5)
        pipeline.keyword_search("test", top_k=5)

        records = pipeline.auditor.records
        assert len(records) == 3
        assert records[0].operation == "upsert"
        assert records[1].operation == "search"
        assert records[2].operation == "search"

    def test_degraded_to_keyword_on_vector_failure(self):
        """Verify vector embedding failures degrade gracefully to keyword-only indexing."""
        def fail_embedding(text):
            """fail embedding."""
            raise RuntimeError("embedding unavailable")

        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=32, embed_func=fail_embedding),
        )
        chunks = _make_chunks(2, prefix="降级测试")

        count = pipeline.index_chunks(chunks)

        assert count == len(chunks)
        assert pipeline.vector_store.size == 0
        keyword_results = pipeline.keyword_search("降级", top_k=5)
        assert len(keyword_results) > 0
        assert pipeline.auditor.records[0].degraded is True


class TestEndToEnd0402:
    """End-to-end tests for chunking and indexing a document event."""

    def test_full_pipeline_from_event(self):
        """Verify a document event can be chunked and indexed, then found by keyword search."""

        event = make_document_event(
            source_url="https://example.com/filing",
            source_name="sse",
            source_level=SourceLevel.L1,
            title="关于公司经营的公告",
            content="一、经营情况\n本季度现金流改善。\n\n二、财务数据\n净利润增长20%。",
            symbols=["000001.SZ"],
            doc_type="filing",
        )

        chunker = Chunker()
        chunks = chunker.chunk(event)
        assert len(chunks) >= 2

        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )
        count = pipeline.index_chunks(chunks)
        assert count == len(chunks)

        results = pipeline.keyword_search("现金流", top_k=5)
        assert len(results) > 0
        assert any("现金流" in r[0].content for r in results)
