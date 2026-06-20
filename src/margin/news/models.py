"""Data models for the news acquisition layer.

Defines source priority levels, raw content snapshots, normalized document events, and factory
helpers used by the news acquisition pipeline. The pipeline flow is:

1. Discover a URL or API record.
2. Download the original content.
3. Persist an immutable raw snapshot.
4. Identify the format.
5. Extract body text and tables.
6. Deduplicate against existing records.
7. Map securities entities.
8. Assign timestamps and source level.
9. Publish a DocumentEvent to the vectorization queue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Source levels
# ---------------------------------------------------------------------------


class SourceLevel(IntEnum):
    """Source priority level from L1 (highest) to L5 (lowest).

    Levels determine whether a source may directly affect research or portfolio state:

    Attributes:
        L1: Exchange announcements, regulatory filings, and periodic reports.
        L2: Official IR channels, earnings calls, and formal management guidance.
        L3: Hard industry data such as prices, sales volumes, inventory, and tenders.
        L4: Authoritative media and professional research. May only trigger investigation or
            provide supporting context.
        L5: Social media and unverified sources. May only trigger investigation.
    """

    L1 = 1  # Exchange announcements, regulatory filings, and periodic reports.
    L2 = 2  # Official IR channels, earnings calls, and formal management guidance.
    L3 = 3  # Hard industry data such as prices, sales volumes, inventory, and tenders.
    L4 = 4  # Authoritative media and professional research.
    L5 = 5  # Social media and unverified sources.


class DocumentStatus(StrEnum):
    """Processing status controlling whether a document may be used as evidence.

    Attributes:
        READY: Document was parsed successfully and may be used as evidence.
        PARSE_FAILED: Document could not be parsed; only the raw snapshot is available.
    """

    READY = "ready"
    PARSE_FAILED = "parse_failed"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC, assuming UTC for naive values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Raw snapshot
# ---------------------------------------------------------------------------


class RawSnapshot(BaseModel):
    """Immutable snapshot of downloaded original content.

    Captures metadata about the downloaded source, including format, content hash, and storage
    path. Once persisted, a snapshot must not be altered.

    Attributes:
        snapshot_id: Unique identifier for the snapshot.
        source_url: URL from which the content was retrieved.
        content_hash: Cryptographic hash of the raw content.
        content_type: MIME or format category of the content (e.g., pdf, html, json, csv, text).
        raw_size: Size of the raw content in bytes.
        storage_path: Path or URI where the raw content is stored, if available.
        downloaded_at: Timestamp when the download occurred.
        http_status: HTTP response status code, if applicable.
    """

    snapshot_id: str
    source_url: str
    content_hash: str
    content_type: str  # pdf / html / json / csv / text
    raw_size: int = 0
    storage_path: str | None = None
    downloaded_at: datetime = Field(default_factory=utc_now)
    http_status: int | None = None

    model_config = {"frozen": True}

    @field_validator("downloaded_at")
    @classmethod
    def normalize_downloaded_at(cls, value: datetime) -> datetime:
        """Normalize snapshot timestamps to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)


# ---------------------------------------------------------------------------
# Normalized document event
# ---------------------------------------------------------------------------


class DocumentEvent(BaseModel):
    """Normalized document event published after acquisition and enrichment.

    Represents a filing, news article, web page, or industry record that has been downloaded,
    snapshotted, parsed, deduplicated, mapped to securities, and assigned a source level. The
    event is consumed by the vectorization queue for further indexing.

    Attributes:
        event_id: Unique identifier for this event.
        document_id: Unique identifier for the logical document.
        source_url: URL of the original source.
        source_name: Human-readable name of the source.
        source_level: Trust level of the source.
        title: Document title.
        content: Extracted body text, if available.
        content_hash: Hash of the normalized content.
        snapshot_id: Reference to the immutable raw snapshot, if available.
        snapshot_hash: Hash of the immutable raw snapshot, if available.
        symbols: List of security symbols mentioned in the document.
        doc_type: Document category (e.g., filing, news, report, ir, industry, user_file).
        published_at: Official publication timestamp.
        available_at: Timestamp when the document became available to the system.
        retrieved_at: Timestamp when the document was retrieved.
        is_original: Whether this event is the original record rather than a duplicate.
        duplicate_of: Reference to the canonical event ID if this event is a duplicate.
    """

    event_id: str
    document_id: str
    source_url: str
    source_name: str
    source_level: SourceLevel
    title: str
    content: str | None = None
    content_hash: str
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    symbols: tuple[str, ...] = Field(default_factory=tuple)
    doc_type: str = "filing"  # filing / news / report / ir / industry / user_file
    published_at: datetime
    available_at: datetime
    retrieved_at: datetime = Field(default_factory=utc_now)
    processing_status: DocumentStatus = DocumentStatus.READY
    processing_error: str | None = None
    is_original: bool = True
    duplicate_of: str | None = None

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at", "retrieved_at")
    @classmethod
    def normalize_event_timestamp(cls, value: datetime) -> datetime:
        """Normalize event timestamps to UTC for point-in-time comparisons.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    @property
    def can_change_research_state(self) -> bool:
        """Whether this source level is allowed to directly change research or portfolio state.

        Returns:
            True if the source level is L1, L2, or L3. L4 and L5 may only support investigation
            and must not directly alter research or holdings.
        """
        return (
            self.processing_status == DocumentStatus.READY
            and self.source_level <= SourceLevel.L3
        )


# ---------------------------------------------------------------------------
# Source descriptor
# ---------------------------------------------------------------------------


class SourceDescriptor(BaseModel):
    """Registered source descriptor used by the source registry.

    Describes a news or filings source, including its default trust level, access requirements,
    and rate limits.

    Attributes:
        name: Unique name of the source.
        source_type: Source category (e.g., exchange, ir, media, rss, websearch, user).
        default_level: Default trust level assigned to documents from this source.
        url_pattern: URL pattern or base URL for the source, if applicable.
        requires_auth: Whether access to the source requires authentication.
        rate_limit_per_min: Maximum number of requests allowed per minute.
        config: Additional source-specific configuration.
    """

    name: str
    source_type: str  # exchange / ir / media / rss / websearch / user
    default_level: SourceLevel
    url_pattern: str | None = None
    requires_auth: bool = False
    rate_limit_per_min: int = 60
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def compute_content_hash(content: str | bytes) -> str:
    """Compute a SHA-256 hash for the provided content.

    Args:
        content: Text or binary content to hash. Strings are encoded as UTF-8 before hashing.

    Returns:
        A content hash string prefixed with "sha256:".
    """
    import hashlib

    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def make_document_event(
    source_url: str,
    source_name: str,
    source_level: SourceLevel,
    title: str,
    content: str | None = None,
    content_hash: str | None = None,
    symbols: list[str] | None = None,
    doc_type: str = "filing",
    published_at: datetime | None = None,
    available_at: datetime | None = None,
    snapshot_id: str | None = None,
    snapshot_hash: str | None = None,
    processing_status: DocumentStatus = DocumentStatus.READY,
    processing_error: str | None = None,
) -> DocumentEvent:
    """Create a normalized DocumentEvent, auto-generating IDs and content hash.

    Args:
        source_url: URL of the original source.
        source_name: Human-readable name of the source.
        source_level: Trust level of the source.
        title: Document title.
        content: Extracted body text, if available.
        content_hash: Pre-computed content hash. If omitted, a hash is derived from the content
            or title.
        symbols: List of security symbols mentioned in the document.
        doc_type: Document category.
        published_at: Official publication timestamp. Defaults to the current time.
        available_at: Timestamp when the document became available. Defaults to the publication
            time or the current time.
        snapshot_id: Reference to the immutable raw snapshot, if available.

    Returns:
        A frozen DocumentEvent ready for downstream indexing.
    """
    import uuid

    if content_hash is None:
        content_hash = compute_content_hash(content or title)

    now = utc_now()
    return DocumentEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        document_id=f"doc_{uuid.uuid4().hex[:12]}",
        source_url=source_url,
        source_name=source_name,
        source_level=source_level,
        title=title,
        content=content,
        content_hash=content_hash,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        symbols=tuple(symbols or ()),
        doc_type=doc_type,
        published_at=published_at or now,
        available_at=available_at or published_at or now,
        processing_status=processing_status,
        processing_error=processing_error,
    )
