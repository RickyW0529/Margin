"""Parser base contracts for v0.2 text indexing."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from margin.vector.models import SourceLocator


class ParserUnavailable(RuntimeError):
    """Raised when an optional parser dependency is not installed."""


class ParsedBlock(BaseModel):
    """Locator-rich parsed source block."""

    text: str
    block_type: Literal["heading", "paragraph", "table_row", "json_field", "page"]
    locator: SourceLocator
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class DocumentParser(Protocol):
    """Protocol implemented by structured parsers."""

    parser_version: str

    def parse(
        self,
        content: bytes,
        *,
        source_url: str | None = None,
    ) -> list[ParsedBlock]:
        """Parse bytes into locator-rich blocks.

        Args:
            content: Raw document bytes to parse.
            source_url: Optional URL of the original source.

        Returns:
            A list of ``ParsedBlock`` instances with locator metadata.
        """
