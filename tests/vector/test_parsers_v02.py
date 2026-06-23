"""v0.2 structured parser locator tests."""

from __future__ import annotations

from margin.vector.parsers.html import HtmlParser
from margin.vector.parsers.tabular import CsvParser, JsonParser
from margin.vector.parsers.text import PlainTextParser


def test_html_parser_emits_heading_and_dom_locator() -> None:
    """html parser emits heading and dom locator."""
    parser = HtmlParser(parser_version="html-v0.2.0")

    blocks = parser.parse(
        "<html><body><h1>业绩说明</h1><p>收入增长 20%。</p></body></html>".encode(),
        source_url="https://example.com/a.html",
    )

    assert blocks[0].text == "业绩说明"
    assert blocks[0].locator.dom_path.endswith("/h1[1]")
    assert blocks[1].locator.section == "业绩说明"


def test_csv_parser_emits_table_row_and_column_locator() -> None:
    """csv parser emits table row and column locator."""
    parser = CsvParser(parser_version="csv-v0.2.0")

    blocks = parser.parse("项目,金额\n收入,100\n利润,20\n".encode())

    assert blocks[1].locator.table_id == "table-1"
    assert blocks[1].locator.row_id == "row-2"
    assert blocks[1].text == "项目=利润; 金额=20"


def test_json_parser_flattens_scalar_fields() -> None:
    """json parser flattens scalar fields."""
    parser = JsonParser(parser_version="json-v0.2.0")

    blocks = parser.parse(b'{"revenue": 100, "nested": {"profit": 20}}')

    assert [block.text for block in blocks] == ["revenue=100", "nested.profit=20"]
    assert blocks[1].locator.row_id == "nested.profit"


def test_text_parser_keeps_paragraph_quote_span() -> None:
    """text parser keeps paragraph quote span."""
    parser = PlainTextParser(parser_version="text-v0.2.0")

    blocks = parser.parse("第一段。\n\n第二段。".encode())

    assert blocks[1].locator.paragraph_index == 1
    assert blocks[1].locator.quote_span == (6, 10)
