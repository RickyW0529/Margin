"""Tests for hybrid retrieval, reranking, and the retrieval tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from margin.news.models import SourceLevel, make_document_event
from margin.vector.chunker import Chunker
from margin.vector.embedding import EmbeddingPipeline, EmbeddingProvider
from margin.vector.models import make_chunk
from margin.vector.retrieval import (
    HybridRetriever,
    Reranker,
    RetrievalTool,
    SearchConstraints,
)


def _naive(dt: datetime) -> datetime:
    """Strip timezone info from a datetime for naive comparisons.

    Args:
        dt: A datetime value, possibly timezone-aware.

    Returns:
        A naive datetime with the same local values.
    """
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _setup_pipeline(chunks_data: list[tuple[str, str, SourceLevel, datetime]]):
    """Create an ``EmbeddingPipeline`` preloaded with the given chunks.

    Args:
        chunks_data: Tuples of (content, symbol, source_level, published_at).

    Returns:
        An ``EmbeddingPipeline`` with the chunks already indexed.
    """
    provider = EmbeddingProvider(dim=64)
    pipeline = EmbeddingPipeline(embedding_provider=provider)

    chunks = []
    for i, (content, symbol, level, pub_date) in enumerate(chunks_data):
        chunk = make_chunk(
            document_id=f"doc_{symbol}_{content[:5]}",
            content=content,
            symbol=symbol,
            source_level=level,
            published_at=pub_date,
            available_at=pub_date,
            source_url=f"https://example.com/doc_{i}",
            source_name="test",
            paragraph_index=i,
        )
        chunks.append(chunk)
    pipeline.index_chunks(chunks)
    return pipeline


class TestHybridRetriever:
    """Tests for ``HybridRetriever`` combining vector and keyword search with constraints."""

    def test_basic_search(self):
        """Verify hybrid search returns ranked results matching the query."""
        pipeline = _setup_pipeline([
            ("公司经营现金流显著改善", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
            ("公司净利润下降", "000001.SZ", SourceLevel.L2, datetime(2026, 6, 16)),
            ("行业景气度回升", "600000.SH", SourceLevel.L4, datetime(2026, 6, 15)),
        ])

        retriever = HybridRetriever(pipeline)
        constraints = SearchConstraints(
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
        )
        results = retriever.search("现金流", top_k=3, constraints=constraints)

        assert len(results) > 0
        assert results[0].chunk.content == "公司经营现金流显著改善"
        assert results[0].score > 0
        assert results[0].rank == 1

    def test_symbol_filter(self):
        """Verify search constraints restrict results to the requested symbol."""
        pipeline = _setup_pipeline([
            ("现金流改善", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
            ("现金流改善", "600000.SH", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        retriever = HybridRetriever(pipeline)
        constraints = SearchConstraints(
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
        )
        results = retriever.search("现金流", top_k=5, constraints=constraints)

        assert len(results) == 1
        assert results[0].chunk.symbol == "000001.SZ"

    def test_decision_at_filter(self):
        """Verify ``available_at`` must not exceed ``decision_at``."""
        pipeline = _setup_pipeline([
            ("早期数据", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 1)),
            ("未来数据", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 20)),
        ])

        retriever = HybridRetriever(pipeline)
        constraints = SearchConstraints(
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
        )
        results = retriever.search("数据", top_k=5, constraints=constraints)

        assert all(_naive(r.chunk.available_at) <= datetime(2026, 6, 18) for r in results)
        assert any("早期" in r.chunk.content for r in results)
        assert not any("未来" in r.chunk.content for r in results)

    def test_prefer_official_boost(self):
        """Verify ``prefer_official`` boosts L1-L3 sources above L4 sources."""
        pipeline = _setup_pipeline([
            ("官方公告现金流", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
            ("媒体报道现金流", "000001.SZ", SourceLevel.L4, datetime(2026, 6, 17)),
        ])

        retriever = HybridRetriever(pipeline)
        constraints = SearchConstraints(
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            prefer_official=True,
        )
        results = retriever.search("现金流", top_k=5, constraints=constraints)

        assert results[0].chunk.source_level == SourceLevel.L1

    def test_dedup_by_content_hash(self):
        """Verify ``dedup=True`` removes duplicate facts from the result list."""
        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )
        chunks = [
            make_chunk(
                document_id=document_id,
                content="相同的现金流内容",
                symbol="000001.SZ",
                source_level=SourceLevel.L1,
                source_url=f"https://example.com/{document_id}",
                paragraph_index=0,
                published_at=datetime(2026, 6, 17),
                available_at=datetime(2026, 6, 17),
            )
            for document_id in ("doc_1", "doc_2")
        ]
        pipeline.index_chunks(chunks)

        retriever = HybridRetriever(pipeline)
        constraints = SearchConstraints(
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            dedup=True,
        )
        results = retriever.search("现金流", top_k=5, constraints=constraints)

        hashes = [r.chunk.content_hash for r in results]
        assert len(results) == 1
        assert len(hashes) == len(set(hashes))

    def test_dedup_normalizes_case_and_whitespace(self):
        """Verify fact deduplication normalizes case and repeated whitespace."""
        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )
        chunks = [
            make_chunk(
                document_id="doc_1",
                content="Cash Flow Improved",
                symbol="000001.SZ",
                source_url="https://example.com/1",
                paragraph_index=0,
                published_at=datetime(2026, 6, 17),
                available_at=datetime(2026, 6, 17),
            ),
            make_chunk(
                document_id="doc_2",
                content="  cash   flow improved  ",
                symbol="000001.SZ",
                source_url="https://example.com/2",
                paragraph_index=0,
                published_at=datetime(2026, 6, 17),
                available_at=datetime(2026, 6, 17),
            ),
        ]
        pipeline.index_chunks(chunks)

        results = HybridRetriever(pipeline).search(
            "cash flow",
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18),
            ),
        )

        assert len(results) == 1

    def test_score_components_present(self):
        """Verify each result exposes vector, keyword, time-decay, and quality sub-scores."""
        pipeline = _setup_pipeline([
            ("测试内容", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        retriever = HybridRetriever(pipeline)
        results = retriever.search(
            "测试",
            top_k=1,
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18),
            ),
        )

        assert len(results) == 1
        r = results[0]
        assert r.vector_score >= 0
        assert r.keyword_score >= 0
        assert r.time_decay > 0
        assert r.source_quality > 0
        assert r.score > 0

    def test_empty_results(self):
        """Verify an irrelevant query returns an empty result list."""
        pipeline = _setup_pipeline([
            ("完全不相关的内容", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        retriever = HybridRetriever(pipeline)
        results = retriever.search(
            "xyz",
            top_k=5,
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18),
            ),
        )
        assert results == []

    def test_constraints_require_symbol_and_decision_time(self):
        """Verify missing required constraints raise ``ValueError``."""
        pipeline = _setup_pipeline([
            ("证据", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        with pytest.raises(ValueError, match="symbol"):
            HybridRetriever(pipeline).search("证据")

    def test_timezone_offsets_are_compared_in_utc(self):
        """Verify timezone-aware ``available_at`` and ``decision_at`` are compared in UTC."""
        provider = EmbeddingProvider(dim=64)
        pipeline = EmbeddingPipeline(embedding_provider=provider)
        chunk = make_chunk(
            document_id="doc_tz",
            content="时区证据",
            symbol="000001.SZ",
            source_level=SourceLevel.L1,
            published_at=datetime(2026, 6, 18, 9, 0, tzinfo=timezone(timedelta(hours=8))),
            available_at=datetime(2026, 6, 18, 9, 0, tzinfo=timezone(timedelta(hours=8))),
            source_url="https://example.com/tz",
            paragraph_index=0,
        )
        pipeline.index_chunks([chunk])

        results = HybridRetriever(pipeline).search(
            "时区",
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18, 1, 30, tzinfo=UTC),
            ),
        )

        assert len(results) == 1

    def test_multiple_doc_types_are_included(self):
        """Verify search can include chunks from multiple document types."""
        provider = EmbeddingProvider(dim=64)
        pipeline = EmbeddingPipeline(embedding_provider=provider)
        chunks = [
            make_chunk(
                document_id="filing",
                content="公告证据",
                symbol="000001.SZ",
                doc_type="filing",
                source_url="https://example.com/f",
                paragraph_index=0,
                published_at=datetime(2026, 6, 17),
                available_at=datetime(2026, 6, 17),
            ),
            make_chunk(
                document_id="news",
                content="新闻证据",
                symbol="000001.SZ",
                doc_type="news",
                source_url="https://example.com/n",
                paragraph_index=0,
                published_at=datetime(2026, 6, 17),
                available_at=datetime(2026, 6, 17),
            ),
        ]
        pipeline.index_chunks(chunks)

        results = HybridRetriever(pipeline).search(
            "证据",
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18),
                doc_types=["filing", "news"],
            ),
        )

        assert {result.chunk.doc_type.value for result in results} == {"filing", "news"}

    def test_vector_failure_degrades_to_keyword_results(self):
        """Verify vector search failures fall back to keyword-only results."""
        class BrokenVectorStore:
            """Mock vector store that always raises on search."""

            size = 0

            def upsert_batch(self, items):
                """Pretend to upsert but do nothing."""
                return 0

            def search(self, *args, **kwargs):
                """Raise a runtime error simulating vector store unavailability."""
                raise RuntimeError("vector store unavailable")

        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
            vector_store=BrokenVectorStore(),
        )
        chunk = make_chunk(
            document_id="doc",
            content="关键词证据",
            symbol="000001.SZ",
            source_url="https://example.com/evidence",
            paragraph_index=0,
            published_at=datetime(2026, 6, 17),
            available_at=datetime(2026, 6, 17),
        )
        pipeline.index_chunks([chunk])

        results = HybridRetriever(pipeline).search(
            "关键词",
            constraints=SearchConstraints(
                symbol="000001.SZ",
                decision_at=datetime(2026, 6, 18),
            ),
        )

        assert [result.chunk.content for result in results] == ["关键词证据"]


class TestReranker:
    """Tests for ``Reranker`` reordering results by query relevance."""

    def test_rerank_reorders(self):
        """Verify reranking boosts the more relevant chunk to first place."""
        from margin.vector.models import RetrievalResult

        chunks = [
            make_chunk(document_id="d1", content="现金流相关度低"),
            make_chunk(document_id="d2", content="现金流相关度非常高"),
        ]

        results = [
            RetrievalResult(chunk=chunks[0], score=0.6, rank=1),
            RetrievalResult(chunk=chunks[1], score=0.5, rank=2),
        ]

        reranker = Reranker()
        reranked = reranker.rerank("非常", results, top_k=2)

        assert reranked[0].chunk.content == "现金流相关度非常高"

    def test_rerank_preserves_top_k(self):
        """Verify reranking truncates and re-ranks the result list to ``top_k``."""
        from margin.vector.models import RetrievalResult

        chunks = [make_chunk(document_id=f"d{i}", content=f"content {i}") for i in range(5)]
        results = [
            RetrievalResult(chunk=c, score=0.5, rank=i + 1)
            for i, c in enumerate(chunks)
        ]

        reranker = Reranker()
        reranked = reranker.rerank("content", results, top_k=3)
        assert len(reranked) == 3
        assert reranked[0].rank == 1
        assert reranked[2].rank == 3

    def test_custom_rerank_func(self):
        """Verify a custom scoring function controls the reranking order."""
        from margin.vector.models import RetrievalResult

        def custom(query, content):
            return 1.0 if "target" in content else 0.0

        chunks = [
            make_chunk(document_id="d1", content="no match"),
            make_chunk(document_id="d2", content="target content"),
        ]
        results = [
            RetrievalResult(chunk=chunks[0], score=0.9, rank=1),
            RetrievalResult(chunk=chunks[1], score=0.5, rank=2),
        ]

        reranker = Reranker(rerank_func=custom)
        reranked = reranker.rerank("target", results, top_k=2)
        assert reranked[0].chunk.content == "target content"


class TestRetrievalTool:
    """Tests for ``RetrievalTool``, the high-level search interface."""

    def test_search_with_constraints(self):
        """Verify the tool filters by symbol and decision time and returns results."""
        pipeline = _setup_pipeline([
            ("现金流改善公告", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
            ("净利润增长", "000001.SZ", SourceLevel.L2, datetime(2026, 6, 16)),
            ("行业报告", "600000.SH", SourceLevel.L4, datetime(2026, 6, 15)),
        ])

        tool = RetrievalTool(pipeline)
        results = tool.search(
            query="现金流",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            top_k=5,
        )

        assert len(results) > 0
        assert all(r.chunk.symbol == "000001.SZ" for r in results)
        assert all(_naive(r.chunk.available_at) <= datetime(2026, 6, 18) for r in results)

    def test_search_by_symbol(self):
        """Verify ``search_by_symbol`` is a convenient symbol-scoped search."""
        pipeline = _setup_pipeline([
            ("关于000001的公告", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
            ("关于600000的公告", "600000.SH", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        tool = RetrievalTool(pipeline)
        results = tool.search_by_symbol(
            "000001.SZ",
            "公告",
            decision_at=datetime(2026, 6, 18),
            top_k=5,
        )

        assert len(results) > 0
        assert all(r.chunk.symbol == "000001.SZ" for r in results)

    def test_output_has_locator(self):
        """Verify returned chunks expose source URL and paragraph index for citation."""
        pipeline = _setup_pipeline([
            ("有定位的chunk", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        tool = RetrievalTool(pipeline)
        results = tool.search(
            "定位",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            top_k=1,
        )

        assert len(results) == 1
        chunk = results[0].chunk
        assert chunk.source_url is not None
        assert chunk.paragraph_index is not None

    def test_chunk_without_locator_is_rejected(self):
        """Verify chunks lacking source_url or paragraph_index are excluded from results."""
        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )
        chunk = make_chunk(
            document_id="d1",
            content="无定位证据",
            symbol="000001.SZ",
            published_at=datetime(2026, 6, 17),
            available_at=datetime(2026, 6, 17),
        )
        pipeline.index_chunks([chunk])

        results = RetrievalTool(pipeline, use_rerank=False).search(
            "证据",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
        )

        assert results == []

    def test_rerank_disabled(self):
        """Verify retrieval works when the reranker is disabled."""
        pipeline = _setup_pipeline([
            ("现金流内容", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])

        tool = RetrievalTool(pipeline, use_rerank=False)
        results = tool.search(
            "现金流",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            top_k=1,
        )
        assert len(results) == 1

    def test_missing_pit_constraints_are_rejected(self):
        """Verify missing ``decision_at`` raises ``ValueError``."""
        pipeline = _setup_pipeline([
            ("证据", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])
        tool = RetrievalTool(pipeline)

        with pytest.raises(ValueError, match="decision_at"):
            tool.search("证据", symbol="000001.SZ")

    def test_rerank_failure_returns_hybrid_results(self):
        """Verify a broken reranker falls back to the raw hybrid result list."""
        class BrokenReranker:
            """Mock reranker that always raises."""

            def rerank(self, *args, **kwargs):
                """Raise a runtime error simulating reranker unavailability."""
                raise RuntimeError("reranker unavailable")

        pipeline = _setup_pipeline([
            ("现金流证据", "000001.SZ", SourceLevel.L1, datetime(2026, 6, 17)),
        ])
        tool = RetrievalTool(pipeline, reranker=BrokenReranker())

        results = tool.search(
            "现金流",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
        )

        assert len(results) == 1


class TestEndToEnd0403:
    """End-to-end tests for chunking, indexing, and retrieving document events."""

    def test_full_retrieval_pipeline(self):
        """Verify events are chunked, indexed, and retrievable with ranking and constraints."""
        events = [
            make_document_event(
                source_url="https://example.com/filing1",
                source_name="sse",
                source_level=SourceLevel.L1,
                title="关于公司经营的公告",
                content=(
                    "一、经营情况\n本季度现金流改善30%。\n\n"
                    "二、财务数据\n净利润同比增长20%。"
                ),
                symbols=["000001.SZ"],
                doc_type="filing",
                published_at=datetime(2026, 6, 17),
            ),
            make_document_event(
                source_url="https://example.com/news1",
                source_name="media",
                source_level=SourceLevel.L4,
                title="媒体报道公司业绩",
                content="据媒体报道，该公司业绩表现良好。",
                symbols=["000001.SZ"],
                doc_type="news",
                published_at=datetime(2026, 6, 16),
            ),
        ]

        chunker = Chunker()
        all_chunks = chunker.chunk_batch(events)

        pipeline = EmbeddingPipeline(
            embedding_provider=EmbeddingProvider(dim=64),
        )
        pipeline.index_chunks(all_chunks)

        tool = RetrievalTool(pipeline)
        results = tool.search(
            query="现金流",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            top_k=5,
        )

        assert len(results) > 0
        top = results[0]
        assert top.chunk.symbol == "000001.SZ"
        assert _naive(top.chunk.available_at) <= datetime(2026, 6, 18)
        assert top.rank == 1
        assert top.score > 0
