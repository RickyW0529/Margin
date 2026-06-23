"""PDF parser adapter."""

from __future__ import annotations

from margin.vector.models import SourceLocator
from margin.vector.parsers.base import ParsedBlock, ParserUnavailable


class PdfParser:
    """Parse PDFs into page-level blocks using PyMuPDF when installed."""

    def __init__(self, parser_version: str = "pdf-v0.2.0") -> None:
        """Initialize the instance."""
        self.parser_version = parser_version

    def parse(
        self,
        content: bytes,
        *,
        source_url: str | None = None,
    ) -> list[ParsedBlock]:
        """Parse the input and return extracted content."""
        try:
            import fitz  # type: ignore[import-untyped]
        except Exception as exc:  # noqa: BLE001
            raise ParserUnavailable("pdf parser dependency is not installed") from exc

        document = fitz.open(stream=content, filetype="pdf")
        blocks: list[ParsedBlock] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text = page.get_text("text").strip()
            if text:
                blocks.append(
                    ParsedBlock(
                        text=text,
                        block_type="page",
                        locator=SourceLocator(page=page_index + 1),
                        metadata={"source_url": source_url} if source_url else {},
                    )
                )
        return blocks
