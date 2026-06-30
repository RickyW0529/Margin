"""CSV and JSON parser adapters with table/field locators."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from typing import Any

from margin.vector.models import SourceLocator
from margin.vector.parsers.base import ParsedBlock


class CsvParser:
    """Parse CSV rows into table-row blocks."""

    def __init__(self, parser_version: str = "csv-v0.2.0") -> None:
        """Initialize the CSV parser.

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
        """Parse CSV content into table-row blocks with row locators.

        Args:
            content: Raw CSV bytes to parse.
            source_url: Optional URL of the original source.

        Returns:
            A list of ``ParsedBlock`` instances with table and row locators.
        """
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        blocks: list[ParsedBlock] = []
        for row_index, row in enumerate(reader, start=1):
            fields = [f"{key}={value}" for key, value in row.items()]
            blocks.append(
                ParsedBlock(
                    text="; ".join(fields),
                    block_type="table_row",
                    locator=SourceLocator(
                        table_id="table-1",
                        row_id=f"row-{row_index}",
                    ),
                    metadata={"source_url": source_url} if source_url else {},
                )
            )
        return blocks


class JsonParser:
    """Flatten scalar JSON fields into locatable blocks."""

    def __init__(self, parser_version: str = "json-v0.2.0") -> None:
        """Initialize the JSON parser.

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
        """Parse JSON content into flattened scalar field blocks with path locators.

        Args:
            content: Raw JSON bytes to parse.
            source_url: Optional URL of the original source.

        Returns:
            A list of ``ParsedBlock`` instances with JSON path locators.
        """
        payload = json.loads(content.decode("utf-8", errors="replace"))
        blocks: list[ParsedBlock] = []
        for path, value in _flatten(payload):
            blocks.append(
                ParsedBlock(
                    text=f"{path}={value}",
                    block_type="json_field",
                    locator=SourceLocator(row_id=path),
                    metadata={"source_url": source_url} if source_url else {},
                )
            )
        return blocks


def _flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Flatten nested JSON into (path, scalar_value) pairs."""
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(nested, path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]"
            yield from _flatten(nested, path)
    else:
        yield prefix, value
