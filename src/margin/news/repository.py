"""PostgreSQL repositories for news acquisition and WebSearch audit.

Provides SQLAlchemy-backed persistence for document events, raw snapshots, search queries,
outbox messages, duplicate decisions, and repost chains. Repositories use a session factory so
that callers can manage transaction boundaries independently.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentMaterialityScoreRow,
    DocumentOutboxRow,
    DocumentSecurityLinkRow,
    NewsContextBundleRow,
    NewsContextDocumentRow,
    NewsRefreshRunRow,
    NewsRefreshTargetRow,
    RawSnapshotRow,
    RepostEdgeRow,
    SearchQueryRow,
    SearchResultRow,
    SourceCursorRow,
)
from margin.news.models import (
    DocumentEvent,
    DocumentMaterialityScore,
    DocumentSecurityLink,
    DocumentStatus,
    NewsContextBundle,
    NewsContextDocument,
    NewsRefreshRun,
    NewsRefreshStatus,
    NewsTarget,
    NewsTargetStatus,
    NewsTargetWorkItem,
    RawSnapshot,
    SourceLevel,
    TargetReconciliation,
    TargetTriggerType,
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
    status: str = "pending"
    claimed_at: datetime | None = None
    last_error: str | None = None

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
                        status=row.status,
                        claimed_at=row.claimed_at,
                        last_error=row.last_error,
                    )
                )
            return messages

    def add_document_outbox(
        self,
        *,
        event_id: str,
        topic: str,
        status: str = "pending",
        claimed_at: datetime | None = None,
    ) -> int:
        """Insert or update a document outbox row for worker replay."""
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(DocumentOutboxRow).where(
                    DocumentOutboxRow.event_id == event_id,
                    DocumentOutboxRow.topic == topic,
                )
            )
            if existing is not None:
                existing.status = status
                existing.claimed_at = claimed_at
                return int(existing.outbox_id)
            row = DocumentOutboxRow(
                event_id=event_id,
                topic=topic,
                status=status,
                attempts=0,
                created_at=utc_now(),
                claimed_at=claimed_at,
            )
            session.add(row)
            session.flush()
            return int(row.outbox_id)

    def get_outbox_by_event(self, event_id: str, topic: str) -> OutboxMessage | None:
        """Return one outbox row by event/topic."""
        with self._session_factory() as session:
            row = session.scalar(
                select(DocumentOutboxRow).where(
                    DocumentOutboxRow.event_id == event_id,
                    DocumentOutboxRow.topic == topic,
                )
            )
            if row is None:
                return None
            return OutboxMessage(
                outbox_id=row.outbox_id,
                event_id=row.event_id,
                topic=row.topic,
                attempts=row.attempts,
                status=row.status,
                claimed_at=row.claimed_at,
                last_error=row.last_error,
            )

    def claim_outbox_with_lease(
        self,
        topic: str,
        *,
        limit: int = 50,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> list[OutboxMessage]:
        """Claim pending/retryable/expired processing outbox rows."""
        now = now or utc_now()
        cutoff = now - timedelta(seconds=lease_seconds)
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(DocumentOutboxRow)
                .where(
                    DocumentOutboxRow.topic == topic,
                    (
                        DocumentOutboxRow.status.in_(
                            ["pending", "failed_retryable"]
                        )
                        | (
                            (DocumentOutboxRow.status == "processing")
                            & (DocumentOutboxRow.claimed_at < cutoff)
                        )
                    ),
                )
                .order_by(DocumentOutboxRow.created_at, DocumentOutboxRow.outbox_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            messages: list[OutboxMessage] = []
            for row in rows:
                row.status = "processing"
                row.claimed_at = now
                row.attempts += 1
                messages.append(
                    OutboxMessage(
                        outbox_id=row.outbox_id,
                        event_id=row.event_id,
                        topic=row.topic,
                        attempts=row.attempts,
                        status=row.status,
                        claimed_at=row.claimed_at,
                        last_error=row.last_error,
                    )
                )
            return messages

    def mark_outbox_succeeded(self, outbox_id: int) -> None:
        """Mark an outbox row succeeded."""
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "succeeded"
                row.delivered_at = utc_now()

    def mark_outbox_retryable(self, outbox_id: int, error: str) -> None:
        """Mark an outbox row retryable."""
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed_retryable"
                row.last_error = error

    def mark_outbox_failed_final(self, outbox_id: int, error: str) -> None:
        """Mark an outbox row terminal failed."""
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed_final"
                row.last_error = error

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

    def create_news_refresh_run(
        self,
        *,
        run_id: str,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
    ) -> None:
        """Create a target-driven refresh run idempotently."""
        with self._session_factory.begin() as session:
            if session.get(NewsRefreshRunRow, run_id) is None:
                now = utc_now()
                session.add(
                    NewsRefreshRunRow(
                        run_id=run_id,
                        scope_version_id=scope_version_id,
                        quant_run_id=quant_run_id,
                        decision_at=decision_at,
                        status=NewsRefreshStatus.PENDING.value,
                        target_count=0,
                        completed_count=0,
                        failed_final_count=0,
                        created_at=now,
                        error_summary={},
                    )
                )

    def get_news_refresh_run(self, run_id: str) -> NewsRefreshRun | None:
        """Fetch a durable news refresh run summary."""
        with self._session_factory() as session:
            row = session.get(NewsRefreshRunRow, run_id)
            return _news_refresh_run_from_row(row) if row is not None else None

    def update_news_refresh_run_status(
        self,
        run_id: str,
        *,
        status: NewsRefreshStatus,
        error_summary: dict[str, object] | None = None,
    ) -> None:
        """Update a refresh run status without altering target completeness."""
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshRunRow, run_id)
            if row is not None:
                row.status = status.value
                if error_summary is not None:
                    row.error_summary = error_summary

    def upsert_news_targets(self, run_id: str, targets: list[NewsTarget]) -> int:
        """Persist all targets for a run before any external provider calls.

        Returns the total unique target count for the run after the operation.
        """
        with self._session_factory.begin() as session:
            existing_keys = set(
                session.scalars(
                    select(NewsRefreshTargetRow.dedupe_key).where(
                        NewsRefreshTargetRow.run_id == run_id
                    )
                ).all()
            )
            now = utc_now()
            for target in targets:
                if target.dedupe_key in existing_keys:
                    continue
                session.add(
                    NewsRefreshTargetRow(
                        target_id=f"nt_{uuid.uuid4().hex[:16]}",
                        run_id=run_id,
                        dedupe_key=target.dedupe_key,
                        security_id=target.security_id,
                        symbol=target.symbol,
                        name=target.name,
                        trigger_type=target.trigger_type.value,
                        priority=target.priority,
                        status=target.status.value,
                        attempts=target.attempts,
                        next_attempt_at=target.next_attempt_at,
                        last_error_code=target.last_error_code,
                        last_error_message=None,
                        payload=target.model_dump(mode="json"),
                        created_at=now,
                    )
                )
                existing_keys.add(target.dedupe_key)
            session.flush()
            return int(
                session.scalar(
                    select(func.count()).select_from(NewsRefreshTargetRow).where(
                        NewsRefreshTargetRow.run_id == run_id
                    )
                )
                or 0
            )

    def set_news_refresh_target_count(self, run_id: str, target_count: int) -> None:
        """Set the complete target count for a run."""
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshRunRow, run_id)
            if row is not None:
                row.target_count = target_count

    def claim_news_targets(
        self,
        run_id: str,
        *,
        limit: int,
        now: datetime,
    ) -> list[NewsTargetWorkItem]:
        """Claim eligible pending/retry targets for processing."""
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(NewsRefreshTargetRow)
                .where(
                    NewsRefreshTargetRow.run_id == run_id,
                    NewsRefreshTargetRow.status.in_(
                        [
                            NewsTargetStatus.PENDING.value,
                            NewsTargetStatus.RETRY.value,
                        ]
                    ),
                    or_(
                        NewsRefreshTargetRow.next_attempt_at.is_(None),
                        NewsRefreshTargetRow.next_attempt_at <= now,
                    ),
                )
                .order_by(
                    NewsRefreshTargetRow.priority.desc(),
                    NewsRefreshTargetRow.next_attempt_at.asc().nullsfirst(),
                    NewsRefreshTargetRow.created_at.asc(),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            items: list[NewsTargetWorkItem] = []
            for row in rows:
                row.status = NewsTargetStatus.CLAIMED.value
                row.claimed_at = now
                row.attempts += 1
                target = _news_target_from_row(row)
                items.append(
                    NewsTargetWorkItem(
                        target_id=row.target_id,
                        run_id=row.run_id,
                        target=target,
                        claimed_at=now,
                    )
                )
            run = session.get(NewsRefreshRunRow, run_id)
            if run is not None and rows:
                run.status = NewsRefreshStatus.RUNNING.value
                run.started_at = run.started_at or now
            return items

    def mark_news_target_completed(
        self,
        target_id: str,
        event_ids: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Mark a target as completed and retain linked event ids for audit."""
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshTargetRow, target_id)
            if row is not None:
                row.status = NewsTargetStatus.COMPLETED.value
                row.completed_at = utc_now()
                payload = dict(row.payload or {})
                payload["event_ids"] = list(event_ids)
                row.payload = payload

    def mark_news_target_retry(
        self,
        target_id: str,
        *,
        error_code: str,
        error_message: str,
        next_attempt_at: datetime,
    ) -> None:
        """Return a claimed target to retry/backoff state."""
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshTargetRow, target_id)
            if row is not None:
                row.status = NewsTargetStatus.RETRY.value
                row.next_attempt_at = next_attempt_at
                row.last_error_code = error_code
                row.last_error_message = error_message

    def mark_news_target_failed_final(
        self,
        target_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        """Mark a target as terminal failed."""
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshTargetRow, target_id)
            if row is not None:
                row.status = NewsTargetStatus.FAILED_FINAL.value
                row.last_error_code = error_code
                row.last_error_message = error_message
                row.completed_at = utc_now()

    def reconcile_news_refresh_run(self, run_id: str) -> TargetReconciliation:
        """Reconcile target counts and update the run terminal status when possible."""
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(NewsRefreshTargetRow).where(NewsRefreshTargetRow.run_id == run_id)
            ).all()
            counts = {status.value: 0 for status in NewsTargetStatus}
            for row in rows:
                counts[row.status] = counts.get(row.status, 0) + 1
            reconciliation = TargetReconciliation(
                target_count=len(rows),
                pending_count=counts.get(NewsTargetStatus.PENDING.value, 0),
                claimed_count=counts.get(NewsTargetStatus.CLAIMED.value, 0),
                retry_count=counts.get(NewsTargetStatus.RETRY.value, 0),
                completed_count=counts.get(NewsTargetStatus.COMPLETED.value, 0),
                failed_final_count=counts.get(NewsTargetStatus.FAILED_FINAL.value, 0),
                is_terminal=NewsRefreshStatus.is_terminal_counts(
                    target_count=len(rows),
                    completed_count=counts.get(NewsTargetStatus.COMPLETED.value, 0),
                    failed_final_count=counts.get(
                        NewsTargetStatus.FAILED_FINAL.value,
                        0,
                    ),
                ),
            )
            run = session.get(NewsRefreshRunRow, run_id)
            if run is not None:
                run.target_count = reconciliation.target_count
                run.completed_count = reconciliation.completed_count
                run.failed_final_count = reconciliation.failed_final_count
                if reconciliation.is_terminal:
                    run.finished_at = utc_now()
                    run.status = (
                        NewsRefreshStatus.PARTIAL.value
                        if reconciliation.failed_final_count
                        else NewsRefreshStatus.COMPLETED.value
                    )
            return reconciliation

    def add_document_security_link(self, link: DocumentSecurityLink) -> None:
        """Persist a document/security relation idempotently."""
        with self._session_factory.begin() as session:
            row = session.get(
                DocumentSecurityLinkRow,
                (link.event_id, link.security_id),
            )
            if row is None:
                session.add(
                    DocumentSecurityLinkRow(
                        event_id=link.event_id,
                        security_id=link.security_id,
                        symbol=link.symbol,
                        relation_type=link.relation_type,
                        source=link.source,
                        created_at=link.created_at,
                    )
                )
            else:
                row.symbol = link.symbol
                row.relation_type = link.relation_type
                row.source = link.source

    def add_document_materiality_score(self, score: DocumentMaterialityScore) -> None:
        """Persist deterministic materiality score for an event/security pair."""
        if score.event_id is None:
            raise ValueError("event_id is required to persist materiality score")
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(DocumentMaterialityScoreRow).where(
                    DocumentMaterialityScoreRow.event_id == score.event_id,
                    DocumentMaterialityScoreRow.security_id == score.security_id,
                    DocumentMaterialityScoreRow.scoring_version
                    == score.scoring_version,
                )
            )
            if existing is None:
                session.add(_materiality_score_to_row(score))
            else:
                existing.relevance_score = score.relevance_score
                existing.materiality_score = score.materiality_score
                existing.novelty_score = score.novelty_score
                existing.trigger_type = score.trigger_type
                existing.risk_polarity = score.risk_polarity
                existing.is_material = score.is_material
                existing.reason_codes = list(score.reason_codes)
                existing.is_untrusted_external_text = score.is_untrusted_external_text
                existing.can_directly_change_research_state = (
                    score.can_directly_change_research_state
                )

    def list_news_context_documents(
        self,
        *,
        security_id: str,
        max_documents: int,
    ) -> list[NewsContextDocument]:
        """List ranked context candidates for a security."""
        with self._session_factory() as session:
            rows = session.execute(
                select(DocumentEventRow, DocumentMaterialityScoreRow)
                .join(
                    DocumentSecurityLinkRow,
                    DocumentSecurityLinkRow.event_id == DocumentEventRow.event_id,
                )
                .join(
                    DocumentMaterialityScoreRow,
                    (DocumentMaterialityScoreRow.event_id == DocumentEventRow.event_id)
                    & (
                        DocumentMaterialityScoreRow.security_id
                        == DocumentSecurityLinkRow.security_id
                    ),
                )
                .where(DocumentSecurityLinkRow.security_id == security_id)
                .order_by(
                    DocumentEventRow.source_level.asc(),
                    DocumentMaterialityScoreRow.materiality_score.desc(),
                    DocumentMaterialityScoreRow.novelty_score.desc(),
                    DocumentEventRow.published_at.desc(),
                )
                .limit(max_documents)
            ).all()
            documents: list[NewsContextDocument] = []
            for rank, (event, score) in enumerate(rows, start=1):
                documents.append(
                    NewsContextDocument(
                        event_id=event.event_id,
                        title=event.title,
                        source_level=SourceLevel(event.source_level),
                        materiality_score=score.materiality_score,
                        novelty_score=score.novelty_score,
                        published_at=event.published_at,
                        rank=rank,
                    )
                )
            return documents

    def list_target_statuses_for_security(
        self,
        *,
        run_id: str,
        security_id: str,
    ) -> list[NewsTargetStatus]:
        """List target statuses for one security in a refresh run."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(NewsRefreshTargetRow.status)
                .where(
                    NewsRefreshTargetRow.run_id == run_id,
                    NewsRefreshTargetRow.security_id == security_id,
                )
                .order_by(NewsRefreshTargetRow.priority.desc())
            ).all()
            return [NewsTargetStatus(row) for row in rows]

    def add_news_context_bundle(self, bundle: NewsContextBundle) -> None:
        """Persist a context bundle and its ordered document list idempotently."""
        with self._session_factory.begin() as session:
            if session.get(NewsContextBundleRow, bundle.bundle_id) is None:
                session.add(
                    NewsContextBundleRow(
                        bundle_id=bundle.bundle_id,
                        run_id=bundle.run_id,
                        security_id=bundle.security_id,
                        target_completion_state=bundle.target_completion_state,
                        can_support_verified_carry_forward=(
                            bundle.can_support_verified_carry_forward
                        ),
                        incomplete_reason_codes=list(bundle.incomplete_reason_codes),
                        created_at=bundle.created_at,
                    )
                )
            for document in bundle.documents:
                if (
                    session.get(
                        NewsContextDocumentRow,
                        (bundle.bundle_id, document.event_id),
                    )
                    is None
                ):
                    session.add(
                        NewsContextDocumentRow(
                            bundle_id=bundle.bundle_id,
                            event_id=document.event_id,
                            rank=document.rank,
                            selection_reason=document.selection_reason,
                        )
                    )


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


def _news_refresh_run_from_row(row: NewsRefreshRunRow) -> NewsRefreshRun:
    """Map a news refresh run row to its domain summary."""
    return NewsRefreshRun(
        run_id=row.run_id,
        scope_version_id=row.scope_version_id,
        quant_run_id=row.quant_run_id,
        decision_at=row.decision_at,
        status=NewsRefreshStatus(row.status),
        target_count=row.target_count,
        completed_count=row.completed_count,
        failed_final_count=row.failed_final_count,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=row.error_summary or {},
    )


def _news_target_from_row(row: NewsRefreshTargetRow) -> NewsTarget:
    """Map a refresh target row to a domain target preserving current queue state."""
    payload = dict(row.payload or {})
    payload.update(
        {
            "security_id": row.security_id,
            "symbol": row.symbol,
            "name": row.name,
            "trigger_type": TargetTriggerType(row.trigger_type),
            "priority": row.priority,
            "status": NewsTargetStatus(row.status),
            "attempts": row.attempts,
            "next_attempt_at": row.next_attempt_at,
            "last_error_code": row.last_error_code,
        }
    )
    return NewsTarget(**payload)


def _materiality_score_to_row(
    score: DocumentMaterialityScore,
) -> DocumentMaterialityScoreRow:
    """Map a materiality score domain object to an ORM row."""
    if score.event_id is None:
        raise ValueError("event_id is required to map materiality score")
    return DocumentMaterialityScoreRow(
        event_id=score.event_id,
        security_id=score.security_id,
        relevance_score=score.relevance_score,
        materiality_score=score.materiality_score,
        novelty_score=score.novelty_score,
        trigger_type=score.trigger_type,
        risk_polarity=score.risk_polarity,
        is_material=score.is_material,
        reason_codes=list(score.reason_codes),
        scoring_version=score.scoring_version,
        is_untrusted_external_text=score.is_untrusted_external_text,
        can_directly_change_research_state=score.can_directly_change_research_state,
        created_at=score.created_at,
    )
