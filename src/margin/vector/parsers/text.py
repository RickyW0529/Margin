"""Plain text parser with paragraph quote spans."""

from __future__ import annotations

import re

from margin.vector.models import SourceLocator
from margin.vector.parsers.base import ParsedBlock


class PlainTextParser:
    """Parse plain text into paragraph blocks with character spans."""

    def __init__(self, parser_version: str = "text-v0.2.0") -> None:
        """Initialize the plain text parser.

        Args:
            parser_version: Version label recorded in parsed block metadata.
        """
        self.parser_version = parser_version

    def parse(
        self,
        content: bytes,
        *,
        source_url: str | None = None,
    ) -> list[ParsedBlock]:
        """Parse plain text into paragraph blocks with character spans.

        Args:
            content: Raw text bytes to parse.
            source_url: Optional URL of the original source.

        Returns:
            A list of ``ParsedBlock`` instances with paragraph index and quote span.
        """
        text = content.decode("utf-8", errors="replace")
        blocks: list[ParsedBlock] = []
        for index, match in enumerate(re.finditer(r"\S.*?(?=\n\s*\n|$)", text, re.S)):
            paragraph = match.group().strip()
            if not paragraph:
                continue
            start = match.start()
            end = start + len(paragraph)
            blocks.append(
                ParsedBlock(
                    text=paragraph,
                    block_type="paragraph",
                    locator=SourceLocator(
                        paragraph_index=index,
                        quote_span=(start, end),
                    ),
                    metadata={"source_url": source_url} if source_url else {},
                )
            )
        return blocks
