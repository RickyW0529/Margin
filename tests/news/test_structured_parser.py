"""Tests for ``StructuredDocumentParser``.

These tests verify that HTML and CSV inputs are converted into ordered
structured blocks with stable source locators such as sections, paragraph
indices, table ids, and row ids.
"""

from __future__ import annotations

import io

from pypdf import PdfWriter

from margin.news.parsed import StructuredDocumentParser


def test_html_parser_emits_ordered_blocks_with_sections_and_quote_spans():
    """HTML headings and paragraphs are parsed with preserved source locators.

    Verifies that the parser emits heading and paragraph blocks in document
    order, assigns the current section heading to each block, and records the
    paragraph index and quote span for locating text in the original page.
    """
    parser = StructuredDocumentParser()
    document = parser.parse_html(
        "<html><body><h1>年度报告</h1><p>第一段 000001.SZ</p><p>第二段</p></body></html>",
        document_id="doc_html",
        source_url="https://example.com/report.html",
    )

    assert document.document_id == "doc_html"
    assert [block.block_type for block in document.blocks] == [
        "heading",
        "paragraph",
        "paragraph",
    ]
    assert document.blocks[1].section == "年度报告"
    assert document.blocks[1].paragraph_index == 0
    assert document.blocks[1].quote_span is not None


def test_csv_parser_emits_table_rows_with_table_and_row_ids():
    """CSV rows become table blocks with stable table and row identifiers.

    Verifies that the parser emits one block per CSV row, assigns a consistent
    ``table_id`` to all rows, and uses predictable ``row_id`` values.
    """
    parser = StructuredDocumentParser()
    document = parser.parse_csv(
        "symbol,value\n000001.SZ,12\n600000.SH,8\n",
        document_id="doc_csv",
        source_url="file://table.csv",
    )

    assert [block.row_id for block in document.blocks] == ["row_1", "row_2"]
    assert all(block.table_id == "table_1" for block in document.blocks)
    assert "000001.SZ" in document.blocks[0].text


def test_pdf_parser_emits_page_blocks_with_page_numbers():
    """PDF parser must expose page-level locators even when text is sparse."""
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)

    document = StructuredDocumentParser().parse_pdf(
        buffer.getvalue(),
        document_id="doc_pdf",
        source_url="file://report.pdf",
    )

    assert document.blocks[0].block_type == "page"
    assert document.blocks[0].page == 1
