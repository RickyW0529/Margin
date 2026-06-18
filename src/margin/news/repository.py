"""PostgreSQL repositories for news acquisition and WebSearch audit.

Provides SQLAlchemy-backed persistence for document events, raw snapshots, search queries,
outbox messages, duplicate decisions, and repost chains. Repositories use a session factory so
that callers can manage transaction boundaries independently.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentOutboxRow,
    RawSnapshotRow,
    RepostEdgeRow,
    SearchQueryRow,
    SearchResultRow,
    SourceCursorRow,
)
from margin.news.models import (
    DocumentEvent,
    DocumentStatus,
    RawSnapshot,
    SourceLevel,
    utc_now,
)
from margin.news.websearch import SearchQueryRecord, SearchResult


class OutboxMessage(BaseModel):
    """Claimed outbox message.

    Represents a pending document event delivery that has been claimed by a worker for
    processing.

    Attributes:
        outbox_id: Primary key of the outbox row.
        event_id: Foreign key to the document event being delivered.
        topic: Destination topic or queue name.
        attempts: Number of delivery attempts already made.
    """

    outbox_id: int
    event_id: str
    topic: str
    attempts: int

    model_config = {"frozen": True}


class DedupRecord(BaseModel):
    """Dedup decision domain record.

    Mirrors a persisted duplicate decision between a duplicate event and its canonical event.

    Attributes:
        duplicate_event_id: Identifier of the duplicate event.
        canonical_event_id: Identifier of the canonical event.
        reason: Short reason code for the duplicate decision.
        similarity_score: Optional similarity score supporting the decision.
        created_at: Timestamp when the decision was recorded.
    """

    duplicate_event_id: str
    canonical_event_id: str
    reason: str
    similarity_score: float | None
    created_at: datetime

    model_config = {"frozen": True}


class RepostEdge(BaseModel):
    """Repost chain edge domain record.

    Mirrors a persisted parent/child relationship used for repost-chain detection.

    Attributes:
        parent_event_id: Identifier of the canonical parent event.
        child_event_id: Identifier of the repost child event.
        reason: Short reason code for the relationship.
        created_at: Timestamp when the edge was recorded.
    """

    parent_event_id: str
    child_event_id: str
    reason: str
    created_at: datetime

    model_config = {"frozen": True}


class NewsRepository:
    """SQLAlchemy-backed news persistence boundary.

    Encapsulates reads and writes for cursors, snapshots, document events, outbox messages,
    search records, duplicate decisions, and repost edges. Each public method manages its own
    session lifecycle through the injected session factory.

    Attributes:
        _session_factory: Callable that returns a SQLAlchemy ``Session``.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a session factory.

        Args:
            session_factory: Callable returning a SQLAlchemy session. The factory is expected
                to support both plain and context-manager (``begin()``) usage.
        """
        self._session_factory = session_factory

    def upsert_cursor(self, source_name: str, cursor_key: str, cursor_value: str) -> None:
        """Create or update an incremental source cursor.

        Args:
            source_name: Name of the source stream.
            cursor_key: Logical cursor key within the source.
            cursor_value: Opaque cursor value to persist.
        """
        with self._session_factory.begin() as session:
            row = session.get(SourceCursorRow, (source_name, cursor_key))
            if row is None:
                session.add(
                    SourceCursorRow(
                        source_name=source_name,
                        cursor_key=cursor_key,
                        cursor_value=cursor_value,
                        updated_at=utc_now(),
                    )
                )
            else:
                row.cursor_value = cursor_value
                row.updated_at = utc_now()

    def get_cursor(self, source_name: str, cursor_key: str) -> str | None:
        """Read an incremental source cursor.

        Args:
            source_name: Name of the source stream.
            cursor_key: Logical cursor key within the source.

        Returns:
            The persisted cursor value, or None if no cursor exists.
        """
        with self._session_factory() as session:
            row = session.get(SourceCursorRow, (source_name, cursor_key))
            return row.cursor_value if row is not None else None

    def add_snapshot(self, snapshot: RawSnapshot) -> None:
        """Persist immutable snapshot metadata idempotently.

        Args:
            snapshot: Raw snapshot metadata to persist.
        """
        with self._session_factory.begin() as session:
            if session.get(RawSnapshotRow, snapshot.snapshot_id) is None:
                session.add(_snapshot_to_row(snapshot))

    def get_snapshot(self, snapshot_id: str) -> RawSnapshot | None:
        """Fetch immutable snapshot metadata.

        Args:
            snapshot_id: Unique snapshot identifier.

        Returns:
            The raw snapshot, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(RawSnapshotRow, snapshot_id)
            return _snapshot_from_row(row) if row is not None else None

    def add_document_event(
        self,
        event: DocumentEvent,
        *,
        publishable: bool = True,
        topic: str = "vector_index",
    ) -> None:
        """Persist a document event and enqueue it when ready.

        Args:
            event: Document event to persist.
            publishable: Whether to add an outbox row when the event is ready.
            topic: Destination topic for the outbox row.
        """
        with self._session_factory.begin() as session:
            if session.get(DocumentEventRow, event.event_id) is None:
                session.add(_event_to_row(event))
            should_publish = (
                publishable
                and event.processing_status == DocumentStatus.READY
                and session.scalar(
                    select(DocumentOutboxRow.outbox_id).where(
                        DocumentOutboxRow.event_id == event.event_id,
                        DocumentOutboxRow.topic == topic,
                    )
                )
                is None
            )
            if should_publish:
                session.add(
                    DocumentOutboxRow(
                        event_id=event.event_id,
                        topic=topic,
                        status="pending",
                        attempts=0,
                        created_at=utc_now(),
                    )
                )

    def get_document_event(self, event_id: str) -> DocumentEvent | None:
        """Fetch a document event by ID.

        Args:
            event_id: Unique event identifier.

        Returns:
            The document event, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(DocumentEventRow, event_id)
            return _event_from_row(row) if row is not None else None

    def list_unique_events(self) -> list[DocumentEvent]:
        """List canonical events available for cross-process deduplication.

        Returns:
            Events that have not been marked as duplicates, ordered by source level and
            publication time.
        """
        with self._session_factory() as session:
            duplicate_ids = select(DedupRecordRow.duplicate_event_id)
            rows = session.scalars(
                select(DocumentEventRow)
                .where(DocumentEventRow.event_id.not_in(duplicate_ids))
                .order_by(DocumentEventRow.source_level, DocumentEventRow.published_at)
            ).all()
            return [_event_from_row(row) for row in rows]

    def claim_outbox(self, topic: str, limit: int = 50) -> list[OutboxMessage]:
        """Claim pending outbox messages using ``SKIP LOCKED``.

        Args:
            topic: Destination topic to claim messages for.
            limit: Maximum number of messages to claim.

        Returns:
            List of claimed outbox messages.
        """
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(DocumentOutboxRow)
                .where(
                    DocumentOutboxRow.topic == topic,
                    DocumentOutboxRow.status == "pending",
                )
                .order_by(DocumentOutboxRow.created_at, DocumentOutboxRow.outbox_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            now = utc_now()
            messages: list[OutboxMessage] = []
            for row in rows:
                row.status = "claimed"
                row.claimed_at = now
                row.attempts += 1
                messages.append(
                    OutboxMessage(
                        outbox_id=row.outbox_id,
                        event_id=row.event_id,
                        topic=row.topic,
                        attempts=row.attempts,
                    )
                )
            return messages

    def mark_outbox_delivered(self, outbox_id: int) -> None:
        """Mark a claimed outbox message as delivered.

        Args:
            outbox_id: Primary key of the outbox row.
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "delivered"
                row.delivered_at = utc_now()

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        """Mark an outbox message as failed and keep the error for audit.

        Args:
            outbox_id: Primary key of the outbox row.
            error: Error message to record.
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed"
                row.last_error = error

    def add_search_record(self, record: SearchQueryRecord) -> None:
        """Persist a WebSearch query and all result rows idempotently.

        Args:
            record: Search query record to persist.
        """
        with self._session_factory.begin() as session:
            row = session.get(SearchQueryRow, record.query_id)
            if row is None:
                session.add(_search_query_to_row(record))
            else:
                row.query = record.query
                row.searched_at = record.searched_at
                row.api_provider = record.api_provider
                row.result_count = record.result_count
                session.execute(
                    delete(SearchResultRow).where(
                        SearchResultRow.query_id == record.query_id
                    )
                )
            for index, result in enumerate(record.results):
                session.add(_search_result_to_row(record.query_id, index, result))

    def get_search_record(self, query_id: str) -> SearchQueryRecord | None:
        """Fetch a WebSearch query with ordered result rows.

        Args:
            query_id: Unique query identifier.

        Returns:
            The search query record with results, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(SearchQueryRow, query_id)
            if row is None:
                return None
            results = session.scalars(
                select(SearchResultRow)
                .where(SearchResultRow.query_id == query_id)
                .order_by(SearchResultRow.result_index)
            ).all()
            return SearchQueryRecord(
                query_id=row.query_id,
                query=row.query,
                searched_at=row.searched_at,
                api_provider=row.api_provider,
                result_count=row.result_count,
                results=tuple(_search_result_from_row(item) for item in results),
            )

    def add_dedup_record(
        self,
        *,
        duplicate_event_id: str,
        canonical_event_id: str,
        reason: str,
        similarity_score: float | None = None,
    ) -> None:
        """Persist a duplicate decision idempotently.

        Args:
            duplicate_event_id: Identifier of the duplicate event.
            canonical_event_id: Identifier of the canonical event.
            reason: Short reason code for the duplicate decision.
            similarity_score: Optional similarity score supporting the decision.
        """
        with self._session_factory.begin() as session:
            row = session.get(DedupRecordRow, duplicate_event_id)
            if row is None:
                session.add(
                    DedupRecordRow(
                        duplicate_event_id=duplicate_event_id,
                        canonical_event_id=canonical_event_id,
                        reason=reason,
                        similarity_score=similarity_score,
                        created_at=utc_now(),
                    )
                )
            else:
                row.canonical_event_id = canonical_event_id
                row.reason = reason
                row.similarity_score = similarity_score

    def get_dedup_record(self, duplicate_event_id: str) -> DedupRecord | None:
        """Fetch a persisted duplicate decision.

        Args:
            duplicate_event_id: Identifier of the duplicate event.

        Returns:
            The duplicate decision, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(DedupRecordRow, duplicate_event_id)
            return _dedup_from_row(row) if row is not None else None

    def add_repost_edge(
        self,
        *,
        parent_event_id: str,
        child_event_id: str,
        reason: str,
    ) -> None:
        """Persist a repost edge idempotently.

        Args:
            parent_event_id: Identifier of the canonical parent event.
            child_event_id: Identifier of the repost child event.
            reason: Short reason code for the relationship.
        """
        with self._session_factory.begin() as session:
            row = session.get(RepostEdgeRow, (parent_event_id, child_event_id))
            if row is None:
                session.add(
                    RepostEdgeRow(
                        parent_event_id=parent_event_id,
                        child_event_id=child_event_id,
                        reason=reason,
                        created_at=utc_now(),
                    )
                )
            else:
                row.reason = reason

    def list_repost_chain(self, parent_event_id: str) -> list[RepostEdge]:
        """List direct repost edges for a canonical event.

        Args:
            parent_event_id: Identifier of the canonical parent event.

        Returns:
            Repost edges where the given event is the parent.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(RepostEdgeRow)
                .where(RepostEdgeRow.parent_event_id == parent_event_id)
                .order_by(RepostEdgeRow.created_at, RepostEdgeRow.child_event_id)
            ).all()
            return [_repost_from_row(row) for row in rows]


def _snapshot_to_row(snapshot: RawSnapshot) -> RawSnapshotRow:
    """Map a ``RawSnapshot`` domain model to a ``RawSnapshotRow``.

    Args:
        snapshot: Raw snapshot metadata.

    Returns:
        SQLAlchemy row representation.
    """
    return RawSnapshotRow(
        snapshot_id=snapshot.snapshot_id,
        source_url=snapshot.source_url,
        content_hash=snapshot.content_hash,
        content_type=snapshot.content_type,
        raw_size=snapshot.raw_size,
        storage_path=snapshot.storage_path,
        downloaded_at=snapshot.downloaded_at,
        http_status=snapshot.http_status,
    )


def _snapshot_from_row(row: RawSnapshotRow) -> RawSnapshot:
    """Map a ``RawSnapshotRow`` to a ``RawSnapshot`` domain model.

    Args:
        row: SQLAlchemy raw snapshot row.

    Returns:
        Raw snapshot domain model.
    """
    return RawSnapshot(
        snapshot_id=row.snapshot_id,
        source_url=row.source_url,
        content_hash=row.content_hash,
        content_type=row.content_type,
        raw_size=row.raw_size,
        storage_path=row.storage_path,
        downloaded_at=row.downloaded_at,
        http_status=row.http_status,
    )


def _event_to_row(event: DocumentEvent) -> DocumentEventRow:
    """Map a ``DocumentEvent`` domain model to a ``DocumentEventRow``.

    Args:
        event: Document event domain model.

    Returns:
        SQLAlchemy row representation.
    """
    return DocumentEventRow(
        event_id=event.event_id,
        document_id=event.document_id,
        source_url=event.source_url,
        source_name=event.source_name,
        source_level=int(event.source_level),
        title=event.title,
        content=event.content,
        content_hash=event.content_hash,
        snapshot_id=event.snapshot_id,
        snapshot_hash=event.snapshot_hash,
        symbols=list(event.symbols),
        doc_type=event.doc_type,
        published_at=event.published_at,
        available_at=event.available_at,
        retrieved_at=event.retrieved_at,
        processing_status=event.processing_status.value,
        processing_error=event.processing_error,
        is_original=event.is_original,
        duplicate_of=event.duplicate_of,
    )


def _event_from_row(row: DocumentEventRow) -> DocumentEvent:
    """Map a ``DocumentEventRow`` to a ``DocumentEvent`` domain model.

    Args:
        row: SQLAlchemy document event row.

    Returns:
        Document event domain model.
    """
    return DocumentEvent(
        event_id=row.event_id,
        document_id=row.document_id,
        source_url=row.source_url,
        source_name=row.source_name,
        source_level=SourceLevel(row.source_level),
        title=row.title,
        content=row.content,
        content_hash=row.content_hash,
        snapshot_id=row.snapshot_id,
        snapshot_hash=row.snapshot_hash,
        symbols=tuple(row.symbols),
        doc_type=row.doc_type,
        published_at=row.published_at,
        available_at=row.available_at,
        retrieved_at=row.retrieved_at,
        processing_status=DocumentStatus(row.processing_status),
        processing_error=row.processing_error,
        is_original=row.is_original,
        duplicate_of=row.duplicate_of,
    )


def _search_query_to_row(record: SearchQueryRecord) -> SearchQueryRow:
    """Map a ``SearchQueryRecord`` to a ``SearchQueryRow``.

    Args:
        record: Search query domain record.

    Returns:
        SQLAlchemy row representation.
    """
    return SearchQueryRow(
        query_id=record.query_id,
        query=record.query,
        searched_at=record.searched_at,
        api_provider=record.api_provider,
        result_count=record.result_count,
    )


def _search_result_to_row(
    query_id: str,
    index: int,
    result: SearchResult,
) -> SearchResultRow:
    """Map a ``SearchResult`` to a ``SearchResultRow``.

    Args:
        query_id: Parent query identifier.
        index: Position of the result in the query result list.
        result: Search result domain model.

    Returns:
        SQLAlchemy row representation.
    """
    return SearchResultRow(
        query_id=query_id,
        result_index=index,
        url=result.url,
        title=result.title,
        snippet=result.snippet,
        source_level=int(result.source_level),
        has_accessible_original=result.has_accessible_original,
        content_hash=result.content_hash,
        snapshot_id=result.snapshot_id,
    )


def _search_result_from_row(row: SearchResultRow) -> SearchResult:
    """Map a ``SearchResultRow`` to a ``SearchResult`` domain model.

    Args:
        row: SQLAlchemy search result row.

    Returns:
        Search result domain model.
    """
    return SearchResult(
        url=row.url,
        title=row.title,
        snippet=row.snippet,
        source_level=SourceLevel(row.source_level),
        has_accessible_original=row.has_accessible_original,
        content_hash=row.content_hash,
        snapshot_id=row.snapshot_id,
    )


def _dedup_from_row(row: DedupRecordRow) -> DedupRecord:
    """Map a ``DedupRecordRow`` to a ``DedupRecord`` domain model.

    Args:
        row: SQLAlchemy dedup record row.

    Returns:
        Dedup decision domain model.
    """
    return DedupRecord(
        duplicate_event_id=row.duplicate_event_id,
        canonical_event_id=row.canonical_event_id,
        reason=row.reason,
        similarity_score=row.similarity_score,
        created_at=row.created_at,
    )


def _repost_from_row(row: RepostEdgeRow) -> RepostEdge:
    """Map a ``RepostEdgeRow`` to a ``RepostEdge`` domain model.

    Args:
        row: SQLAlchemy repost edge row.

    Returns:
        Repost edge domain model.
    """
    return RepostEdge(
        parent_event_id=row.parent_event_id,
        child_event_id=row.child_event_id,
        reason=row.reason,
        created_at=row.created_at,
    )
