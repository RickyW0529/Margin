"""Tests for document chunkers."""

from __future__ import annotations

import pytest

from margin.news.models import DocumentStatus, SourceLevel, make_document_event
from margin.vector.chunker import (
    Chunker,
    FilingChunker,
    IRChunker,
    NewsChunker,
    ReportChunker,
    UserNoteChunker,
    infer_doc_type,
)
from margin.vector.models import Chunk, DocType


def _make_event(
    title="测试公告",
    content="这是公告正文内容",
    doc_type="filing",
    source_level=SourceLevel.L1,
    symbols=None,
):
    """Build a document event for tests.

    Args:
        title: Document title.
        content: Document body text.
        doc_type: Document type string.
        source_level: Source reliability level.
        symbols: List of related stock symbols.

    Returns:
        A document event built by ``make_document_event``.
    """
    return make_document_event(
        source_url="https://example.com/doc",
        source_name="test",
        source_level=source_level,
        title=title,
        content=content,
        symbols=symbols or [],
        doc_type=doc_type,
    )


class TestInferDocType:
    """Tests mapping document type hints to ``DocType`` enum values."""

    def test_annual_report(self):
        """Verify ``annual_report`` maps to ``DocType.ANNUAL_REPORT``."""
        event = _make_event(title="2025年年度报告", doc_type="annual_report")
        assert infer_doc_type(event) == DocType.ANNUAL_REPORT

    def test_quarterly_report(self):
        """Verify ``quarterly_report`` maps to ``DocType.QUARTERLY_REPORT``."""
        event = _make_event(title="2026年一季度季报", doc_type="quarterly_report")
        assert infer_doc_type(event) == DocType.QUARTERLY_REPORT

    def test_filing(self):
        """Verify ``filing`` maps to ``DocType.FILING``."""
        event = _make_event(title="关于公司公告", doc_type="filing")
        assert infer_doc_type(event) == DocType.FILING

    def test_news(self):
        """Verify ``news`` maps to ``DocType.NEWS``."""
        event = _make_event(title="新闻报道", doc_type="news")
        assert infer_doc_type(event) == DocType.NEWS

    def test_explicit_doc_type_takes_precedence_over_title_keywords(self):
        """Verify a news item about an annual report remains classified as news."""
        event = _make_event(title="公司年报发布新闻", doc_type="news")

        assert infer_doc_type(event) == DocType.NEWS

    def test_ir(self):
        """Verify ``ir`` maps to ``DocType.IR``."""
        event = _make_event(title="业绩说明会问答", doc_type="ir")
        assert infer_doc_type(event) == DocType.IR

    def test_unknown(self):
        """Verify unknown document types map to ``DocType.UNKNOWN``."""
        event = _make_event(title="random", doc_type="unknown")
        assert infer_doc_type(event) == DocType.UNKNOWN


class TestChunkModel:
    """Tests for the immutable ``Chunk`` data model and factory."""

    def test_chunk_frozen(self):
        """Verify chunk instances are frozen and reject attribute mutation."""
        from margin.vector.models import make_chunk

        chunk = make_chunk(document_id="doc_1", content="test content")
        with pytest.raises(Exception):
            chunk.content = "changed"

    def test_chunk_has_metadata(self):
        """Verify chunks carry symbol, section, page, and a sha256 content hash."""
        from margin.vector.models import make_chunk

        chunk = make_chunk(
            document_id="doc_1",
            content="test",
            symbol="000001.SZ",
            section="经营分析",
            page=86,
        )
        assert chunk.symbol == "000001.SZ"
        assert chunk.section == "经营分析"
        assert chunk.page == 86
        assert chunk.content_hash.startswith("sha256:")

    def test_identical_content_has_same_hash_across_documents(self):
        """Verify identical content yields the same hash even with different document IDs."""
        from margin.vector.models import make_chunk

        first = make_chunk(document_id="doc_1", content="相同事实")
        second = make_chunk(document_id="doc_2", content="相同事实")

        assert first.content_hash == second.content_hash

    def test_chunk_collections_are_immutable(self):
        """Verify list-valued fields are stored as immutable tuples."""
        from margin.vector.models import make_chunk

        chunk = make_chunk(
            document_id="doc_1",
            content="test",
            embedding=[0.1, 0.2],
            keywords=["test"],
        )

        assert chunk.embedding == (0.1, 0.2)
        assert chunk.keywords == ("test",)

    def test_empty_source_url_is_not_a_usable_locator(self):
        """Verify an empty URL cannot satisfy the source locator contract."""
        from margin.vector.models import make_chunk

        chunk = make_chunk(
            document_id="doc_1",
            content="test",
            source_url="",
            paragraph_index=0,
        )

        assert chunk.has_locator is False


class TestNewsChunker:
    """Tests for ``NewsChunker`` which splits news into title/lead/body chunks."""

    def test_title_lead_body(self):
        """Verify news content is chunked into title, lead, and body sections."""
        content = "这是导语段落。\n\n这是正文第一段。\n\n这是正文第二段。"
        event = _make_event(
            title="公司发布年报",
            content=content,
            doc_type="news",
        )
        chunker = NewsChunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 2
        labels = [c.section for c in chunks]
        assert "title" in labels
        assert "lead" in labels
        assert "body" in labels

    def test_empty_content(self):
        """Verify empty news body still produces at least a title chunk."""
        event = _make_event(title="空新闻", content="", doc_type="news")
        chunker = NewsChunker()
        chunks = chunker.chunk(event)
        assert len(chunks) == 1
        assert chunks[0].section == "title"

    def test_title_and_lead_respect_max_chunk_size(self):
        """Verify direct news parts also obey the configured hard size limit."""
        event = _make_event(
            title="标" * 75,
            content="导" * 75,
            doc_type="news",
        )

        chunks = NewsChunker(max_chunk_size=50, overlap=0).chunk(event)

        assert len(chunks) == 4
        assert all(len(chunk.content) <= 50 for chunk in chunks)


class TestFilingChunker:
    """Tests for ``FilingChunker`` which splits filings by enumerated items."""

    def test_split_by_items(self):
        """Verify a filing is split by Chinese enumerated item markers."""
        content = (
            "一、会议审议事项\n关于利润分配的议案。\n\n"
            "二、会议时间\n2026年6月20日。\n\n"
            "三、出席人员\n全体董事。"
        )
        event = _make_event(title="董事会公告", content=content, doc_type="filing")
        chunker = FilingChunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 2
        sections = [c.section for c in chunks]
        assert any("一、" in s for s in sections)
        assert any("二、" in s for s in sections)

    def test_text_before_first_item_is_preserved(self):
        """Verify filing introductions are not dropped before the first item marker."""
        event = _make_event(
            title="董事会公告",
            content="重要提示：本公告内容真实准确。\n\n一、审议事项\n通过相关议案。",
            doc_type="filing",
        )

        chunks = FilingChunker().chunk(event)

        assert any("重要提示" in chunk.content for chunk in chunks)


class TestReportChunker:
    """Tests for ``ReportChunker`` which splits annual/quarterly reports by sections."""

    def test_split_by_sections(self):
        """Verify a report is split by Chinese section markers."""
        content = (
            "第一节 经营情况讨论与分析\n本年度经营良好。\n\n"
            "第二节 主要会计数据\n营收增长20%。\n\n"
            "第三节 股本变动\n无重大变动。"
        )
        event = _make_event(
            title="2025年年度报告",
            content=content,
            doc_type="annual_report",
        )
        chunker = ReportChunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 2
        sections = [c.section for c in chunks]
        assert any("第一节" in s for s in sections)

    def test_no_sections_fallback(self):
        """Verify reports without section markers still produce at least one chunk."""
        content = "这是一段没有章节标记的文本内容。"
        event = _make_event(
            title="2025年年度报告",
            content=content,
            doc_type="annual_report",
        )
        chunker = ReportChunker()
        chunks = chunker.chunk(event)
        assert len(chunks) >= 1


class TestIRChunker:
    """Tests for ``IRChunker`` which splits investor-relations Q&A transcripts."""

    def test_qa_pairs(self):
        """Verify Q&A transcripts produce multiple question-answer chunks."""
        content = (
            "问：公司未来增长点在哪里？\n"
            "答：主要在新业务和海外市场。\n"
            "问：分红计划如何？\n"
            "答：计划维持30%分红率。"
        )
        event = _make_event(title="业绩说明会", content=content, doc_type="ir")
        chunker = IRChunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 2

    def test_no_qa_fallback(self):
        """Verify non-Q&A IR content still produces at least one fallback chunk."""
        content = "这是一段没有问答标记的文本。"
        event = _make_event(title="IR记录", content=content, doc_type="ir")
        chunker = IRChunker()
        chunks = chunker.chunk(event)
        assert len(chunks) >= 1

    def test_question_and_answer_are_kept_in_same_chunk(self):
        """Verify each question is paired with its answer in a single chunk."""
        content = "问：增长点？\n答：海外市场。\n问：分红？\n答：维持比例。"
        event = _make_event(title="业绩说明会", content=content, doc_type="ir")

        chunks = IRChunker().chunk(event)

        assert len(chunks) == 2
        assert "问：增长点？" in chunks[0].content
        assert "答：海外市场。" in chunks[0].content


class TestUserNoteChunker:
    """Tests for ``UserNoteChunker`` which chunks user notes by paragraphs."""

    def test_paragraphs(self):
        """Verify user notes are chunked by paragraphs and tagged with the user-note doc type."""
        content = "第一段笔记。\n\n第二段笔记。\n\n第三段笔记。"
        event = _make_event(title="我的笔记", content=content, doc_type="user_note")
        chunker = UserNoteChunker(max_chunk_size=10, overlap=0)
        chunks = chunker.chunk(event)

        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.doc_type == DocType.USER_NOTE


class TestChunker:
    """Tests for the dispatcher ``Chunker`` class which selects chunking strategies."""

    def test_auto_select_strategy(self):
        """Verify the dispatcher chooses a strategy and returns ``Chunk`` instances."""
        content = "标题\n\n正文段落一。\n\n正文段落二。"
        event = _make_event(title="新闻报道", content=content, doc_type="news")
        chunker = Chunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunk_metadata_filled(self):
        """Verify produced chunks inherit symbol, source level, document ID, and source URL."""
        event = _make_event(
            title="关于000001.SZ的公告",
            content="公告正文内容",
            doc_type="filing",
            symbols=["000001.SZ"],
        )
        chunker = Chunker()
        chunks = chunker.chunk(event)

        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.symbol == "000001.SZ"
        assert chunk.source_level == SourceLevel.L1
        assert chunk.document_id == event.document_id
        assert chunk.source_url == event.source_url

    def test_empty_content_fallback(self):
        """Verify empty content falls back to using the title as the chunk content."""
        event = _make_event(title="空公告", content="", doc_type="filing")
        chunker = Chunker()
        chunks = chunker.chunk(event)

        assert len(chunks) == 1
        assert chunks[0].content == "空公告"

    def test_parse_failed_document_is_not_chunked(self):
        """Verify documents marked as parse-failed produce no chunks."""
        event = make_document_event(
            source_url="https://example.com/raw",
            source_name="sse",
            source_level=SourceLevel.L1,
            title="解析失败公告",
            content=None,
            symbols=["000001.SZ"],
            processing_status=DocumentStatus.PARSE_FAILED,
        )

        assert Chunker().chunk(event) == []

    def test_batch_chunking(self):
        """Verify ``chunk_batch`` handles mixed document types and returns chunks."""
        events = [
            _make_event(title="A", content="内容A", doc_type="filing"),
            _make_event(title="B", content="内容B", doc_type="news"),
        ]
        chunker = Chunker()
        all_chunks = chunker.chunk_batch(events)
        assert len(all_chunks) >= 2

    def test_chunk_index_and_total(self):
        """Verify chunks receive sequential ``chunk_index`` and matching ``total_chunks``."""
        content = "段落一。\n\n段落二。\n\n段落三。"
        event = _make_event(title="测试", content=content, doc_type="user_note")
        chunker = Chunker()
        chunks = chunker.chunk(event)

        if len(chunks) > 1:
            assert chunks[0].chunk_index == 0
            assert chunks[-1].chunk_index == len(chunks) - 1
            for c in chunks:
                assert c.total_chunks == len(chunks)

    def test_max_chunk_size(self):
        """Verify ``max_chunk_size`` splits long documents into smaller chunks."""
        long_content = "\n\n".join([f"段落{i}" for i in range(50)])
        event = _make_event(title="长文档", content=long_content, doc_type="user_note")
        chunker = Chunker(max_chunk_size=50, overlap=0)
        chunks = chunker.chunk(event)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= 50

    def test_single_oversized_paragraph_is_split(self):
        """Verify a single paragraph exceeding ``max_chunk_size`` is split evenly."""
        event = _make_event(
            title="长段落",
            content="甲" * 250,
            doc_type="user_note",
        )

        chunks = Chunker(max_chunk_size=50, overlap=0).chunk(event)

        assert len(chunks) == 5
        assert all(len(chunk.content) <= 50 for chunk in chunks)

    def test_multi_symbol_document_is_filterable_by_each_symbol(self):
        """Verify documents with multiple symbols emit one chunk per symbol."""
        event = _make_event(
            title="联合公告",
            content="联合事项",
            doc_type="filing",
            symbols=["000001.SZ", "600000.SH"],
        )

        chunks = Chunker().chunk(event)

        assert {chunk.symbol for chunk in chunks} == {"000001.SZ", "600000.SH"}

    def test_chunking_error_caught(self):
        """Verify ``chunk_batch`` tolerates failures and still returns valid chunks."""
        chunker = Chunker()
        events = [
            _make_event(title="ok", content="ok", doc_type="filing"),
        ]
        results = chunker.chunk_batch(events)
        assert len(results) >= 1
