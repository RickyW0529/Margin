"""Structured parser adapters for v0.2 text indexing."""

from margin.vector.parsers.base import DocumentParser, ParsedBlock, ParserUnavailable
from margin.vector.parsers.html import HtmlParser
from margin.vector.parsers.tabular import CsvParser, JsonParser
from margin.vector.parsers.text import PlainTextParser

__all__ = [
    "CsvParser",
    "DocumentParser",
    "HtmlParser",
    "JsonParser",
    "ParsedBlock",
    "ParserUnavailable",
    "PlainTextParser",
]
