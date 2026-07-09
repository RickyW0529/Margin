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
    """A parsed source block with exact source locator metadata.."""

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
    """Structured parsed document consumed by locator-preserving chunking.."""

    document_id: str
    source_url: str | None = None
    title: str | None = None
    blocks: tuple[ParsedBlock, ...] = Field(default_factory=tuple)
    parse_status: str = "ready"
    parse_error: str | None = None

    model_config = {"frozen": True}


class StructuredDocumentParser:
    """Parser that emits ordered blocks for HTML, PDF text, CSV, JSON, and plain text.."""

    def parse_html(
        self,
        html: str | bytes,
        *,
        document_id: str,
        source_url: str | None = None,
    ) -> ParsedDocument:
        """Parse HTML headings and paragraphs into ordered blocks.

        Args:
            html: str | bytes: .
            document_id: str: .
            source_url: str | None: .

        Returns:
            ParsedDocument: .
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
            content: str | bytes: .
            document_id: str: .
            source_url: str | None: .

        Returns:
            ParsedDocument: .
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
            content: str | bytes: .
            document_id: str: .
            source_url: str | None: .

        Returns:
            ParsedDocument: .
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
            content: bytes: .
            document_id: str: .
            source_url: str | None: .

        Returns:
            ParsedDocument: .
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
            content: str | bytes: .
            document_id: str: .
            source_url: str | None: .

        Returns:
            ParsedDocument: .
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
