"""Tests for the structured block chunker.

Verifies that ``Chunker`` splits parsed document blocks into smaller chunks while
preserving structural metadata (page, section, paragraph, table row) and adjusting
quote character spans to each split boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.models import SourceLevel, make_document_event
from margin.news.parsed import ParsedBlock, ParsedDocument
from margin.vector.chunker import Chunker


def test_chunker_preserves_structured_locators_and_adjusts_quote_spans():
    """Splitting a block must inherit locators and remap quote spans per chunk.

    The chunker receives a single paragraph block with page/section/paragraph/table/row
    metadata and a quote span covering the full text. It should produce multiple chunks,
    each keeping the same structured locators, while the quote span is clipped to the
    character range covered by that chunk.
    """
    event = make_document_event(
        source_url="https://example.com/report.html",
        source_name="sse",
        source_level=SourceLevel.L1,
        title="报告",
        content="",
        symbols=["000001.SZ"],
        published_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    parsed = ParsedDocument(
        document_id=event.document_id,
        source_url=event.source_url,
        title="报告",
        blocks=(
            ParsedBlock(
                block_id="b1",
                block_type="paragraph",
                text="经营现金流改善，净利润增长。",
                page=3,
                section="经营情况",
                paragraph_index=2,
                table_id="table_1",
                row_id="row_2",
                quote_span=(20, 34),
            ),
        ),
    )

    chunks = Chunker(max_chunk_size=8, overlap=0).chunk_parsed(parsed, event)

    assert len(chunks) > 1
    assert all(chunk.page == 3 for chunk in chunks)
    assert all(chunk.section == "经营情况" for chunk in chunks)
    assert all(chunk.paragraph_index == 2 for chunk in chunks)
    assert all(chunk.table_id == "table_1" for chunk in chunks)
    assert all(chunk.row_id == "row_2" for chunk in chunks)
    assert chunks[0].quote_span == (20, 28)
    assert chunks[1].quote_span == (28, 34)
