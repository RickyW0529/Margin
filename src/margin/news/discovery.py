"""Discovery models and protocols for incremental filing acquisition."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class DiscoveredDocument(BaseModel):
    """A document discovered before download and normalization.."""

    external_id: str
    title: str
    source_url: str
    published_at: datetime
    cursor: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("published_at")
    @classmethod
    def normalize_published_at(cls, value: datetime) -> datetime:
        """Normalize exchange timestamps to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


class DiscoveryConnector(Protocol):
    """Connector that discovers document URLs incrementally.."""

    def discover(
        self,
        cursor: str | None,
        limit: int,
    ) -> list[DiscoveredDocument]:
        """Discover a batch of documents from the source.

        Args:
            cursor: str | None: .
            limit: int: .

        Returns:
            list[DiscoveredDocument]: .
        """
