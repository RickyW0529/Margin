"""Structured parsed document models and parsers.

Defines block-oriented parsed document models and a parser that emits ordered blocks for HTML,
CSV, JSON, and plain text sources. Each block preserves source locators such as section,
paragraph index, table row, and quote span so that downstream chunking can cite exact source
positions.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Literal

from pydantic import BaseModel, Field


class ParsedBlock(BaseModel):
    """A parsed source block with exact source locator metadata.

    Attributes:
        block_id: Unique identifier for the block.
        block_type: Semantic type of the block (heading, paragraph, table_row, page, json_row,
            text).
        text: Extracted text content of the block.
        page: Optional page number for paginated sources.
        section: Optional section or heading context.
        paragraph_index: Optional paragraph index within the section.
        table_id: Optional table identifier for table rows.
        row_id: Optional row identifier for table or JSON rows.
        quote_span: Optional character span (start, end) of the text in the original source.
    """

    block_id: str
    block_type: Literal["heading", "paragraph", "table_row", "page", "json_row", "text"]
    text: str
    page: int | None = None
    section: str | None = None
    paragraph_index: int | None = None
    table_id: str | None = None
    row_id: str | None = None
    quote_span: tuple[int, int] | None = None

    model_config = {"frozen": True}


class ParsedDocument(BaseModel):
    """Structured parsed document consumed by locator-preserving chunking.

    Attributes:
        document_id: Unique identifier for the parsed document.
        source_url: Optional URL of the original source.
        title: Optional document title.
        blocks: Ordered tuple of parsed blocks.
        parse_status: Status of parsing (ready or failed).
        parse_error: Optional error message when parsing fails.
    """

    document_id: str
    source_url: str | None = None
    title: str | None = None
    blocks: tuple[ParsedBlock, ...] = Field(default_factory=tuple)
    parse_status: str = "ready"
    parse_error: str | None = None

    model_config = {"frozen": True}


class StructuredDocumentParser:
    """Parser that emits ordered blocks for HTML, PDF text, CSV, JSON, and plain text.

    Each parse method returns a ``ParsedDocument`` whose blocks preserve source locators for
    downstream citation and chunking.
    """

    def parse_html(
        self,
        html: str | bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse HTML headings and paragraphs into ordered blocks.

        Args:
            html: HTML content as text or bytes.
            document_id: Unique identifier for the parsed document.
            source_url: Optional URL of the original source.

        Returns:
            Parsed document containing headings and paragraph blocks.
        """
        from bs4 import BeautifulSoup

        text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
        soup = BeautifulSoup(text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        blocks: list[ParsedBlock] = []
        section: str | None = None
        paragraph_index = 0

        for node in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            value = node.get_text(" ", strip=True)
            if not value:
                continue
            start = text.find(value)
            quote_span = (start, start + len(value)) if start >= 0 else None
            if node.name in {"h1", "h2", "h3"}:
                section = value
                block_type = "heading"
                index = None
            else:
                block_type = "paragraph"
                index = paragraph_index
                paragraph_index += 1
            blocks.append(
                ParsedBlock(
                    block_id=f"blk_{len(blocks) + 1}",
                    block_type=block_type,
                    text=value,
                    section=section,
                    paragraph_index=index,
                    quote_span=quote_span,
                )
            )

        return ParsedDocument(
            document_id=document_id,
            source_url=source_url,
            title=title or (blocks[0].text if blocks else None),
            blocks=tuple(blocks),
        )

    def parse_csv(
        self,
        content: str | bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse CSV rows into table blocks with row locators.

        Args:
            content: CSV content as text or bytes.
            document_id: Unique identifier for the parsed document.
            source_url: Optional URL of the original source.

        Returns:
            Parsed document containing one block per CSV row.
        """
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        reader = csv.DictReader(io.StringIO(text))
        blocks: list[ParsedBlock] = []
        for index, row in enumerate(reader, start=1):
            row_text = " | ".join(f"{key}: {value}" for key, value in row.items())
            start = text.find(next(iter(row.values()), ""))
            blocks.append(
                ParsedBlock(
                    block_id=f"blk_{index}",
                    block_type="table_row",
                    text=row_text,
                    table_id="table_1",
                    row_id=f"row_{index}",
                    quote_span=(start, start + len(row_text)) if start >= 0 else None,
                )
            )
        return ParsedDocument(
            document_id=document_id,
            source_url=source_url,
            title=source_url,
            blocks=tuple(blocks),
        )

    def parse_json(
        self,
        content: str | bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse JSON objects or arrays into structured row blocks.

        Args:
            content: JSON content as text or bytes.
            document_id: Unique identifier for the parsed document.
            source_url: Optional URL of the original source.

        Returns:
            Parsed document containing one block per JSON row.
        """
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
        blocks = [
            ParsedBlock(
                block_id=f"blk_{index}",
                block_type="json_row",
                text=json.dumps(row, ensure_ascii=False, sort_keys=True),
                row_id=f"row_{index}",
            )
            for index, row in enumerate(rows, start=1)
        ]
        return ParsedDocument(
            document_id=document_id,
            source_url=source_url,
            title=source_url,
            blocks=tuple(blocks),
        )

    def parse_pdf(
        self,
        content: bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse PDF pages into page blocks using pypdf.

        Args:
            content: PDF content as bytes.
            document_id: Unique identifier for the parsed document.
            source_url: Optional URL of the original source.

        Returns:
            Parsed document containing one block per PDF page.
        """
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        blocks: list[ParsedBlock] = []
        for index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or f"page_{index}"
            blocks.append(
                ParsedBlock(
                    block_id=f"page_{index}",
                    block_type="page",
                    text=page_text,
                    page=index,
                    quote_span=(0, len(page_text)),
                )
            )
        title = None
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title)
        return ParsedDocument(
            document_id=document_id,
            source_url=source_url,
            title=title or source_url,
            blocks=tuple(blocks),
        )

    def parse_text(
        self,
        content: str | bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse plain text paragraphs.

        Args:
            content: Plain text content as text or bytes.
            document_id: Unique identifier for the parsed document.
            source_url: Optional URL of the original source.

        Returns:
            Parsed document containing one block per paragraph.
        """
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        blocks: list[ParsedBlock] = []
        offset = 0
        for index, paragraph in enumerate(part.strip() for part in text.split("\n\n")):
            if not paragraph:
                continue
            start = text.find(paragraph, offset)
            offset = start + len(paragraph) if start >= 0 else offset
            blocks.append(
                ParsedBlock(
                    block_id=f"blk_{len(blocks) + 1}",
                    block_type="paragraph",
                    text=paragraph,
                    paragraph_index=index,
                    quote_span=(start, start + len(paragraph)) if start >= 0 else None,
                )
            )
        return ParsedDocument(
            document_id=document_id,
            source_url=source_url,
            title=blocks[0].text[:80] if blocks else source_url,
            blocks=tuple(blocks),
        )
