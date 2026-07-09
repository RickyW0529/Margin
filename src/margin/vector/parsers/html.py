"""HTML parser with heading, section, and DOM locator metadata."""

from __future__ import annotations

from html.parser import HTMLParser

from margin.vector.models import SourceLocator
from margin.vector.parsers.base import ParsedBlock


class HtmlParser:
    """Parse simple HTML into heading/paragraph blocks with DOM paths.."""

    def __init__(self, parser_version: str = "html-v0.2.0") -> None:
        """Initialize the HTML parser.

        Args:
            parser_version: str: .

        Returns:
            None: .
        """
        self.parser_version = parser_version

    def parse(
        self,
        content: bytes,
        *,
        source_url: str | None = None,
    ) -> list[ParsedBlock]:
        """Parse HTML content into heading and paragraph blocks with DOM paths.

        Args:
            content: bytes: .
            source_url: str | None: .

        Returns:
            list[ParsedBlock]: .
        """
        parser = _BlockHtmlParser(source_url=source_url)
        parser.feed(content.decode("utf-8", errors="replace"))
        return parser.blocks


class _BlockHtmlParser(HTMLParser):
    """Internal HTML parser that emits heading and paragraph blocks with DOM paths.."""

    def __init__(self, *, source_url: str | None) -> None:
        """Initialize the instance.

        Args:
            source_url: str | None: .

        Returns:
            None: .
        """
        super().__init__()
        self.source_url = source_url
        self.blocks: list[ParsedBlock] = []
        self._stack: list[str] = []
        self._tag_counts: dict[str, int] = {}
        self._current_tag: str | None = None
        self._current_path: str | None = None
        self._section: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        """Handle an opening HTML tag.

        Args:
            tag: str: .
            attrs: Any: .

        Returns:
            None: .
        """
        count = self._tag_counts.get(tag, 0) + 1
        self._tag_counts[tag] = count
        self._stack.append(f"{tag}[{count}]")
        self._current_tag = tag
        self._current_path = "/" + "/".join(self._stack)

    def handle_endtag(self, tag: str) -> None:
        """Handle a closing HTML tag.

        Args:
            tag: str: .

        Returns:
            None: .
        """
        if self._stack:
            self._stack.pop()
        self._current_tag = self._stack[-1].split("[", maxsplit=1)[0] if self._stack else None
        self._current_path = "/" + "/".join(self._stack) if self._stack else None

    def handle_data(self, data: str) -> None:
        """Handle HTML text data.

        Args:
            data: str: .

        Returns:
            None: .
        """
        text = data.strip()
        if not text or self._current_tag not in {"h1", "h2", "h3", "p"}:
            return
        is_heading = self._current_tag in {"h1", "h2", "h3"}
        locator = SourceLocator(
            section=text if is_heading else self._section,
            dom_path=self._current_path,
        )
        self.blocks.append(
            ParsedBlock(
                text=text,
                block_type="heading" if is_heading else "paragraph",
                locator=locator,
                metadata={"source_url": self.source_url} if self.source_url else {},
            )
        )
        if is_heading:
            self._section = text
