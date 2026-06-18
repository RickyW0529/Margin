"""SQLAlchemy models for news acquisition, search, and dedup persistence.

Maps domain entities such as raw snapshots, document events, web search queries, and dedup
records to PostgreSQL tables. JSONB columns are used for structured fields such as symbol lists.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class SourceCursorRow(Base):
    """Restart-safe incremental cursor per source stream.

    Tracks the last consumed cursor for a given source/key combination so that incremental
    fetchers can resume without duplication after a restart.

    Attributes:
        source_name: Name of the source stream.
        cursor_key: Logical cursor key within the source.
        cursor_value: Opaque cursor value used to resume ingestion.
        updated_at: Timestamp when the cursor was last updated.
    """

    __tablename__ = "source_cursors"

    source_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RawSnapshotRow(Base):
    """Immutable raw downloaded content snapshot metadata.

    Stores metadata for a persisted raw snapshot. The actual byte content is referenced by
    ``storage_path`` and is treated as immutable once written.

    Attributes:
        snapshot_id: Unique identifier for the snapshot.
        source_url: URL from which the content was retrieved.
        content_hash: Cryptographic hash of the raw content.
        content_type: MIME or format category of the content (e.g., pdf, html, json).
        raw_size: Size of the raw content in bytes.
        storage_path: Path or URI where the raw content is stored, if available.
        downloaded_at: Timestamp when the download occurred.
        http_status: HTTP response status code, if applicable.
    """

    __tablename__ = "raw_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)


class DocumentEventRow(Base):
    """Persisted normalized document event.

    Represents a filing, news article, web page, or industry record that has been downloaded,
    snapshotted, parsed, and assigned a source level. Indexes support time-series and URL lookups.

    Attributes:
        event_id: Unique identifier for this event.
        document_id: Unique identifier for the logical document.
        source_url: URL of the original source.
        source_name: Human-readable name of the source.
        source_level: Trust level of the source as an integer.
        title: Document title.
        content: Extracted body text, if available.
        content_hash: Hash of the normalized content.
        snapshot_id: Reference to the immutable raw snapshot, if available.
        snapshot_hash: Hash of the immutable raw snapshot, if available.
        symbols: List of security symbols mentioned in the document.
        doc_type: Document category (e.g., filing, news, report, ir, industry).
        published_at: Official publication timestamp.
        available_at: Timestamp when the document became available to the system.
        retrieved_at: Timestamp when the document was retrieved.
        processing_status: Processing status controlling whether the document may be used.
        processing_error: Error message when processing fails.
        is_original: Whether this event is the original record rather than a duplicate.
        duplicate_of: Reference to the canonical event ID if this event is a duplicate.
    """

    __tablename__ = "document_events"
    __table_args__ = (
        Index("ix_document_events_symbol_time", "symbols", "published_at"),
        Index("ix_document_events_source_url", "source_url"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_level: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_snapshots.snapshot_id", ondelete="SET NULL")
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(96))
    symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_error: Mapped[str | None] = mapped_column(Text)
    is_original: Mapped[bool] = mapped_column(nullable=False)
    duplicate_of: Mapped[str | None] = mapped_column(String(64))


class DocumentOutboxRow(Base):
    """Transactional outbox row for document event consumers.

    Supports exactly-once-ish delivery of document events to downstream topics such as the
    vector indexing queue. Workers claim pending rows with ``SKIP LOCKED``.

    Attributes:
        outbox_id: Auto-incrementing primary key.
        event_id: Foreign key to the document event being published.
        topic: Destination topic or queue name.
        status: Delivery status (pending, claimed, delivered, failed).
        attempts: Number of delivery attempts made.
        last_error: Last delivery error message, if any.
        created_at: Timestamp when the outbox row was created.
        claimed_at: Timestamp when the row was last claimed.
        delivered_at: Timestamp when the row was marked as delivered.
    """

    __tablename__ = "document_outbox"
    __table_args__ = (
        UniqueConstraint("event_id", "topic", name="uq_document_outbox_event_topic"),
        Index("ix_document_outbox_status_topic", "topic", "status", "created_at"),
    )

    outbox_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchQueryRow(Base):
    """Immutable web search query audit record.

    Stores the query text, provider, result count, and timestamp for compliance tracing and
    to avoid redundant API calls.

    Attributes:
        query_id: Unique identifier for the query record.
        query: Search query string.
        searched_at: Timestamp when the search was performed.
        api_provider: Name of the API provider that served the query.
        result_count: Number of results returned.
    """

    __tablename__ = "search_queries"

    query_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    api_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)


class SearchResultRow(Base):
    """Persisted raw WebSearch result.

    Captures each result returned for a query, including its source level, accessibility flag,
    and optional snapshot metadata.

    Attributes:
        result_id: Auto-incrementing primary key.
        query_id: Foreign key to the parent search query.
        result_index: Zero-based position in the result list.
        url: Result URL.
        title: Result title.
        snippet: Result snippet or abstract.
        source_level: Source level assigned to the result.
        has_accessible_original: Whether accessible original content is available.
        content_hash: Hash of the original content snapshot, if available.
        snapshot_id: Identifier of the downloaded snapshot, if available.
    """

    __tablename__ = "search_results"
    __table_args__ = (
        UniqueConstraint("query_id", "result_index", name="uq_search_result_index"),
        Index("ix_search_results_url", "url"),
    )

    result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(
        ForeignKey("search_queries.query_id", ondelete="CASCADE"),
        nullable=False,
    )
    result_index: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    source_level: Mapped[int] = mapped_column(Integer, nullable=False)
    has_accessible_original: Mapped[bool] = mapped_column(nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(96))
    snapshot_id: Mapped[str | None] = mapped_column(String(64))


class DedupRecordRow(Base):
    """Persisted duplicate decision.

    Records that one event was judged a duplicate of another canonical event, along with the
    reason and an optional similarity score.

    Attributes:
        duplicate_event_id: Foreign key to the duplicate event; primary key.
        canonical_event_id: Foreign key to the canonical event.
        reason: Short reason code describing why the event was marked duplicate.
        similarity_score: Optional similarity score supporting the decision.
        created_at: Timestamp when the decision was recorded.
    """

    __tablename__ = "dedup_records"

    duplicate_event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    canonical_event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RepostEdgeRow(Base):
    """Canonical repost chain edge.

    Tracks parent/child relationships between events for repost-chain detection and
    earliest-source retention.

    Attributes:
        parent_event_id: Foreign key to the canonical parent event; part of the primary key.
        child_event_id: Foreign key to the repost child event; part of the primary key.
        reason: Short reason code describing the relationship.
        created_at: Timestamp when the edge was recorded.
    """

    __tablename__ = "repost_edges"

    parent_event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    child_event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
