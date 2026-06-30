"""v0.2 structured parser locator tests.

Verifies that HTML, CSV, JSON, and plain-text parsers emit ``ParsedBlock`` objects
with correct source locators (DOM path, table row, paragraph index, quote span).
"""

from __future__ import annotations

from margin.vector.parsers.html import HtmlParser
from margin.vector.parsers.tabular import CsvParser, JsonParser
from margin.vector.parsers.text import PlainTextParser


def test_html_parser_emits_heading_and_dom_locator() -> None:
    """HTML parser must emit heading text and a DOM-path locator.

    Verifies that ``HtmlParser`` produces blocks with heading text, a DOM path
    ending in the heading tag, and a section attribute matching the heading.
    """
    parser = HtmlParser(parser_version="html-v0.2.0")

    blocks = parser.parse(
        "<html><body><h1>业绩说明</h1><p>收入增长 20%。</p></body></html>".encode(),
        source_url="https://example.com/a.html",
    )

    assert blocks[0].text == "业绩说明"
    assert blocks[0].locator.dom_path.endswith("/h1[1]")
    assert blocks[1].locator.section == "业绩说明"


def test_csv_parser_emits_table_row_and_column_locator() -> None:
    """CSV parser must emit table-row blocks with row and column locators.

    Verifies that ``CsvParser`` assigns table and row IDs and formats row content
    as ``column=value`` pairs.
    """
    parser = CsvParser(parser_version="csv-v0.2.0")

    blocks = parser.parse("项目,金额\n收入,100\n利润,20\n".encode())

    assert blocks[1].locator.table_id == "table-1"
    assert blocks[1].locator.row_id == "row-2"
    assert blocks[1].text == "项目=利润; 金额=20"


def test_json_parser_flattens_scalar_fields() -> None:
    """JSON parser must flatten nested scalar fields into key-path blocks.

    Verifies that ``JsonParser`` produces one block per scalar field with
    dot-separated key paths and matching row IDs.
    """
    parser = JsonParser(parser_version="json-v0.2.0")

    blocks = parser.parse(b'{"revenue": 100, "nested": {"profit": 20}}')

    assert [block.text for block in blocks] == ["revenue=100", "nested.profit=20"]
    assert blocks[1].locator.row_id == "nested.profit"


def test_text_parser_keeps_paragraph_quote_span() -> None:
    """Plain-text parser must preserve paragraph index and quote span.

    Verifies that ``PlainTextParser`` assigns sequential paragraph indices and
    computes quote spans covering the full paragraph text.
    """
    parser = PlainTextParser(parser_version="text-v0.2.0")

    blocks = parser.parse("第一段。\n\n第二段。".encode())

    assert blocks[1].locator.paragraph_index == 1
    assert blocks[1].locator.quote_span == (6, 10)
