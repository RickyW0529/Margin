"""Discovery models and protocols for incremental filing acquisition."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class DiscoveredDocument(BaseModel):
    """A document discovered before download and normalization.

    Attributes:
        external_id: Identifier assigned by the upstream source.
        title: Document title.
        source_url: URL where the document can be retrieved.
        published_at: Official publication timestamp.
        cursor: Optional opaque cursor used for incremental discovery.
        metadata: Additional source-specific metadata.
    """

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
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)


class DiscoveryConnector(Protocol):
    """Connector that discovers document URLs incrementally."""

    def discover(
        self,
        cursor: str | None,
        limit: int,
    ) -> list[DiscoveredDocument]:
        """Discover a batch of documents from the source.

        Args:
            cursor: Opaque cursor from a previous discovery pass, or None for the first pass.
            limit: Maximum number of documents to return.

        Returns:
            List of discovered documents ordered from oldest to newest where possible.
        """
