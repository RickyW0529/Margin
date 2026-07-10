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
from sqlalchemy.orm import Session

from margin.news.agentic_models import (
    NewsAgentRun,
    NewsAgentRunStatus,
    NewsAgentTask,
    NewsArticleFinding,
    NewsSearchPlan,
    NewsSecurityBrief,
)
from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentMaterialityScoreRow,
    DocumentOutboxRow,
    DocumentSecurityLinkRow,
    NewsAgentRunRow,
    NewsAgentTaskRow,
    NewsArticleFindingRow,
    NewsContextBundleRow,
    NewsContextDocumentRow,
    NewsRefreshRunRow,
    NewsRefreshTargetRow,
    NewsSearchPlanRow,
    NewsSecurityBriefRow,
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
from margin.sql.news_queries import (
    claimable_news_targets,
    delete_search_results_by_query,
    document_event_by_document_id,
    document_events_by_ids,
    materiality_score_by_event_security_version,
    news_agent_tasks_by_run,
    news_article_findings_by_run,
    news_context_documents,
    news_search_plans_by_run,
    news_security_briefs_by_run,
    news_target_count_by_run,
    news_target_dedupe_keys_by_run,
    news_target_statuses_by_run_security,
    news_targets_by_run,
    outbox_by_event_topic,
    outbox_claimable_by_topic,
    outbox_id_by_event_topic,
    outbox_pending_by_topic,
    repost_edges_by_parent,
    search_results_by_query,
    unique_document_events,
)


class OutboxMessage(BaseModel):
    """Claimed outbox message.."""

    outbox_id: int
    event_id: str
    topic: str
    attempts: int
    status: str = "pending"
    claimed_at: datetime | None = None
    last_error: str | None = None

    model_config = {"frozen": True}


class DedupRecord(BaseModel):
    """Dedup decision domain record.."""

    duplicate_event_id: str
    canonical_event_id: str
    reason: str
    similarity_score: float | None
    created_at: datetime

    model_config = {"frozen": True}


class RepostEdge(BaseModel):
    """Repost chain edge domain record.."""

    parent_event_id: str
    child_event_id: str
    reason: str
    created_at: datetime

    model_config = {"frozen": True}


class NewsRepository:
    """SQLAlchemy-backed news persistence boundary.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a session factory.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def upsert_cursor(self, source_name: str, cursor_key: str, cursor_value: str) -> None:
        """Create or update an incremental source cursor.

        Args:
            source_name: str: .
            cursor_key: str: .
            cursor_value: str: .

        Returns:
            None: .
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
            source_name: str: .
            cursor_key: str: .

        Returns:
            str | None: .
        """
        with self._session_factory() as session:
            row = session.get(SourceCursorRow, (source_name, cursor_key))
            return row.cursor_value if row is not None else None

    def add_snapshot(self, snapshot: RawSnapshot) -> None:
        """Persist immutable snapshot metadata idempotently.

        Args:
            snapshot: RawSnapshot: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(RawSnapshotRow, snapshot.snapshot_id) is None:
                session.add(_snapshot_to_row(snapshot))

    def get_snapshot(self, snapshot_id: str) -> RawSnapshot | None:
        """Fetch immutable snapshot metadata.

        Args:
            snapshot_id: str: .

        Returns:
            RawSnapshot | None: .
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
            event: DocumentEvent: .
            publishable: bool: .
            topic: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            if session.get(DocumentEventRow, event.event_id) is None:
                session.add(_event_to_row(event))
            should_publish = (
                publishable
                and event.processing_status == DocumentStatus.READY
                and session.scalar(outbox_id_by_event_topic(event.event_id, topic)) is None
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
            event_id: str: .

        Returns:
            DocumentEvent | None: .
        """
        with self._session_factory() as session:
            row = session.get(DocumentEventRow, event_id)
            return _event_from_row(row) if row is not None else None

    def get_document_event_by_document_id(self, document_id: str) -> DocumentEvent | None:
        """Fetch the latest event for one canonical document identifier."""
        with self._session_factory() as session:
            row = session.scalar(document_event_by_document_id(document_id))
            return _event_from_row(row) if row is not None else None

    def list_unique_events(self) -> list[DocumentEvent]:
        """List canonical events available for cross-process deduplication.

        Returns:
            list[DocumentEvent]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(unique_document_events()).all()
            return [_event_from_row(row) for row in rows]

    def claim_outbox(self, topic: str, limit: int = 50) -> list[OutboxMessage]:
        """Claim pending outbox messages using ``SKIP LOCKED``.

        Args:
            topic: str: .
            limit: int: .

        Returns:
            list[OutboxMessage]: .
        """
        with self._session_factory.begin() as session:
            rows = session.scalars(outbox_pending_by_topic(topic, limit)).all()
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
        """Insert or update a document outbox row for worker replay.

        Args:
            event_id: str: .
            topic: str: .
            status: str: .
            claimed_at: datetime | None: .

        Returns:
            int: .
        """
        with self._session_factory.begin() as session:
            existing = session.scalar(outbox_by_event_topic(event_id, topic))
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
        """Return one outbox row by event/topic.

        Args:
            event_id: str: .
            topic: str: .

        Returns:
            OutboxMessage | None: .
        """
        with self._session_factory() as session:
            row = session.scalar(outbox_by_event_topic(event_id, topic))
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
        """Claim pending/retryable/expired processing outbox rows.

        Args:
            topic: str: .
            limit: int: .
            now: datetime | None: .
            lease_seconds: int: .

        Returns:
            list[OutboxMessage]: .
        """
        now = now or utc_now()
        cutoff = now - timedelta(seconds=lease_seconds)
        with self._session_factory.begin() as session:
            rows = session.scalars(outbox_claimable_by_topic(topic, cutoff, limit)).all()
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
        """Mark an outbox row succeeded.

        Args:
            outbox_id: int: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "succeeded"
                row.delivered_at = utc_now()

    def mark_outbox_retryable(self, outbox_id: int, error: str) -> None:
        """Mark an outbox row retryable.

        Args:
            outbox_id: int: .
            error: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed_retryable"
                row.last_error = error

    def mark_outbox_failed_final(self, outbox_id: int, error: str) -> None:
        """Mark an outbox row terminal failed.

        Args:
            outbox_id: int: .
            error: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed_final"
                row.last_error = error

    def mark_outbox_delivered(self, outbox_id: int) -> None:
        """Mark a claimed outbox message as delivered.

        Args:
            outbox_id: int: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "delivered"
                row.delivered_at = utc_now()

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        """Mark an outbox message as failed and keep the error for audit.

        Args:
            outbox_id: int: .
            error: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(DocumentOutboxRow, outbox_id)
            if row is not None:
                row.status = "failed"
                row.last_error = error

    def add_search_record(self, record: SearchQueryRecord) -> None:
        """Persist a WebSearch query and all result rows idempotently.

        Args:
            record: SearchQueryRecord: .

        Returns:
            None: .
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
                session.execute(delete_search_results_by_query(record.query_id))
            for index, result in enumerate(record.results):
                session.add(_search_result_to_row(record.query_id, index, result))

    def get_search_record(self, query_id: str) -> SearchQueryRecord | None:
        """Fetch a WebSearch query with ordered result rows.

        Args:
            query_id: str: .

        Returns:
            SearchQueryRecord | None: .
        """
        with self._session_factory() as session:
            row = session.get(SearchQueryRow, query_id)
            if row is None:
                return None
            results = session.scalars(search_results_by_query(query_id)).all()
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
            duplicate_event_id: str: .
            canonical_event_id: str: .
            reason: str: .
            similarity_score: float | None: .

        Returns:
            None: .
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
            duplicate_event_id: str: .

        Returns:
            DedupRecord | None: .
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
            parent_event_id: str: .
            child_event_id: str: .
            reason: str: .

        Returns:
            None: .
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
            parent_event_id: str: .

        Returns:
            list[RepostEdge]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(repost_edges_by_parent(parent_event_id)).all()
            return [_repost_from_row(row) for row in rows]

    def create_news_refresh_run(
        self,
        *,
        run_id: str,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
    ) -> None:
        """Create a target-driven refresh run idempotently.

        Args:
            run_id: str: .
            scope_version_id: str: .
            quant_run_id: str: .
            decision_at: datetime: .

        Returns:
            None: .
        """
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
        """Fetch a durable news refresh run summary.

        Args:
            run_id: str: .

        Returns:
            NewsRefreshRun | None: .
        """
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
        """Update a refresh run status without altering target completeness.

        Args:
            run_id: str: .
            status: NewsRefreshStatus: .
            error_summary: dict[str, object] | None: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshRunRow, run_id)
            if row is not None:
                row.status = status.value
                if error_summary is not None:
                    row.error_summary = error_summary

    def upsert_news_targets(self, run_id: str, targets: list[NewsTarget]) -> int:
        """Persist all targets for a run before any external provider calls.

        Args:
            run_id: str: .
            targets: list[NewsTarget]: .

        Returns:
            int: .
        """
        with self._session_factory.begin() as session:
            existing_keys = set(session.scalars(news_target_dedupe_keys_by_run(run_id)).all())
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
            return int(session.scalar(news_target_count_by_run(run_id)) or 0)

    def set_news_refresh_target_count(self, run_id: str, target_count: int) -> None:
        """Set the complete target count for a run.

        Args:
            run_id: str: .
            target_count: int: .

        Returns:
            None: .
        """
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
        """Claim eligible pending/retry targets for processing.

        Args:
            run_id: str: .
            limit: int: .
            now: datetime: .

        Returns:
            list[NewsTargetWorkItem]: .
        """
        with self._session_factory.begin() as session:
            rows = session.scalars(
                claimable_news_targets(
                    run_id,
                    [
                        NewsTargetStatus.PENDING.value,
                        NewsTargetStatus.RETRY.value,
                    ],
                    now,
                    limit,
                )
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
        """Mark a target as completed and retain linked event ids for audit.

        Args:
            target_id: str: .
            event_ids: list[str] | tuple[str, ...]: .

        Returns:
            None: .
        """
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
        """Return a claimed target to retry/backoff state.

        Args:
            target_id: str: .
            error_code: str: .
            error_message: str: .
            next_attempt_at: datetime: .

        Returns:
            None: .
        """
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
        """Mark a target as terminal failed.

        Args:
            target_id: str: .
            error_code: str: .
            error_message: str: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsRefreshTargetRow, target_id)
            if row is not None:
                row.status = NewsTargetStatus.FAILED_FINAL.value
                row.last_error_code = error_code
                row.last_error_message = error_message
                row.completed_at = utc_now()

    def reconcile_news_refresh_run(self, run_id: str) -> TargetReconciliation:
        """Reconcile target counts and update the run terminal status when possible.

        Args:
            run_id: str: .

        Returns:
            TargetReconciliation: .
        """
        with self._session_factory.begin() as session:
            rows = session.scalars(news_targets_by_run(run_id)).all()
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
        """Persist a document/security relation idempotently.

        Args:
            link: DocumentSecurityLink: .

        Returns:
            None: .
        """
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
        """Persist deterministic materiality score for an event/security pair.

        Args:
            score: DocumentMaterialityScore: .

        Returns:
            None: .
        """
        if score.event_id is None:
            raise ValueError("event_id is required to persist materiality score")
        with self._session_factory.begin() as session:
            existing = session.scalar(
                materiality_score_by_event_security_version(
                    score.event_id,
                    score.security_id,
                    score.scoring_version,
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
        """List ranked context candidates for a security.

        Args:
            security_id: str: .
            max_documents: int: .

        Returns:
            list[NewsContextDocument]: .
        """
        with self._session_factory() as session:
            rows = session.execute(news_context_documents(security_id, max_documents)).all()
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
        """List target statuses for one security in a refresh run.

        Args:
            run_id: str: .
            security_id: str: .

        Returns:
            list[NewsTargetStatus]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_target_statuses_by_run_security(run_id, security_id)).all()
            return [NewsTargetStatus(row) for row in rows]

    def add_news_context_bundle(self, bundle: NewsContextBundle) -> None:
        """Persist a context bundle and its ordered document list idempotently.

        Args:
            bundle: NewsContextBundle: .

        Returns:
            None: .
        """
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

    def add_news_agent_run(self, run: NewsAgentRun) -> None:
        """Persist one agentic news acquisition run idempotently.

        Args:
            run: NewsAgentRun: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsAgentRunRow, run.run_id)
            if row is None:
                session.add(_news_agent_run_to_row(run))
            else:
                row.status = run.status.value
                row.target_count = run.target_count
                row.include_near_threshold = run.include_near_threshold
                row.config_hash = run.config_hash
                row.started_at = run.started_at
                row.finished_at = run.finished_at
                row.error_summary = run.error_summary

    def update_news_agent_run_status(
        self,
        run_id: str,
        *,
        status: NewsAgentRunStatus,
        error_summary: dict[str, object] | None = None,
    ) -> None:
        """Update an agentic run status and optional error summary.

        Args:
            run_id: str: .
            status: NewsAgentRunStatus: .
            error_summary: dict[str, object] | None: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsAgentRunRow, run_id)
            if row is not None:
                row.status = status.value
                if error_summary is not None:
                    row.error_summary = dict(error_summary)
                if status in {
                    NewsAgentRunStatus.COMPLETED,
                    NewsAgentRunStatus.COMPLETED_EMPTY,
                    NewsAgentRunStatus.PARTIAL,
                    NewsAgentRunStatus.FAILED,
                }:
                    row.finished_at = utc_now()

    def get_news_agent_run(self, run_id: str) -> NewsAgentRun | None:
        """Fetch one agentic news acquisition run.

        Args:
            run_id: str: .

        Returns:
            NewsAgentRun | None: .
        """
        with self._session_factory() as session:
            row = session.get(NewsAgentRunRow, run_id)
            return _news_agent_run_from_row(row) if row is not None else None

    def add_news_agent_task(self, task: NewsAgentTask) -> None:
        """Persist one agentic task audit row idempotently.

        Args:
            task: NewsAgentTask: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsAgentTaskRow, task.task_id)
            if row is None:
                session.add(_news_agent_task_to_row(task))
            else:
                row.status = task.status.value
                row.response_hash = task.response_hash
                row.error_code = task.error_code
                row.error_message = task.error_message
                row.payload = task.payload
                row.completed_at = task.completed_at

    def list_news_agent_tasks(self, run_id: str) -> list[NewsAgentTask]:
        """List agentic task audit rows for one run.

        Args:
            run_id: str: .

        Returns:
            list[NewsAgentTask]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_agent_tasks_by_run(run_id)).all()
            return [_news_agent_task_from_row(row) for row in rows]

    def add_news_search_plan(self, plan: NewsSearchPlan) -> None:
        """Persist a reviewed security-level search plan.

        Args:
            plan: NewsSearchPlan: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsSearchPlanRow, plan.plan_id)
            if row is None:
                session.add(_news_search_plan_to_row(plan))
            else:
                row.queries = list(plan.queries)
                row.review_status = plan.review_status
                row.fallback_used = plan.fallback_used
                row.prompt_version = plan.prompt_version
                row.prompt_hash = plan.prompt_hash
                row.response_hash = plan.response_hash

    def list_news_search_plans(self, run_id: str) -> list[NewsSearchPlan]:
        """List reviewed search plans for one agentic run.

        Args:
            run_id: str: .

        Returns:
            list[NewsSearchPlan]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_search_plans_by_run(run_id)).all()
            return [_news_search_plan_from_row(row) for row in rows]

    def add_news_article_finding(self, finding: NewsArticleFinding) -> None:
        """Persist an article-level finding.

        Args:
            finding: NewsArticleFinding: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsArticleFindingRow, finding.finding_id)
            if row is None:
                session.add(_news_article_finding_to_row(finding))
            else:
                row.key_points = list(finding.key_points)
                row.materiality = finding.materiality
                row.sentiment = finding.sentiment
                row.risk_flags = list(finding.risk_flags)
                row.cited_spans = list(finding.cited_spans)
                row.review_status = finding.review_status
                row.confidence = finding.confidence
                row.response_hash = finding.response_hash

    def list_news_article_findings(
        self,
        run_id: str,
        security_id: str | None = None,
    ) -> list[NewsArticleFinding]:
        """List article findings for one agentic run.

        Args:
            run_id: str: .
            security_id: str | None: .

        Returns:
            list[NewsArticleFinding]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_article_findings_by_run(run_id, security_id)).all()
            return [_news_article_finding_from_row(row) for row in rows]

    def add_news_security_brief(self, brief: NewsSecurityBrief) -> None:
        """Persist a derived security-level news brief.

        Args:
            brief: NewsSecurityBrief: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            row = session.get(NewsSecurityBriefRow, brief.brief_id)
            if row is None:
                session.add(_news_security_brief_to_row(brief))
            else:
                row.summary = brief.summary
                row.finding_ids = list(brief.finding_ids)
                row.source_event_ids = list(brief.source_event_ids)
                row.is_derived = brief.is_derived
                row.trust_level = brief.trust_level
                row.response_hash = brief.response_hash

    def list_news_security_briefs(self, run_id: str) -> list[NewsSecurityBrief]:
        """List derived security-level briefs for one run.

        Args:
            run_id: str: .

        Returns:
            list[NewsSecurityBrief]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(news_security_briefs_by_run(run_id)).all()
            return [_news_security_brief_from_row(row) for row in rows]

    def list_document_events_by_ids(self, event_ids: list[str]) -> list[DocumentEvent]:
        """List document events by IDs.

        Args:
            event_ids: list[str]: .

        Returns:
            list[DocumentEvent]: .
        """
        if not event_ids:
            return []
        with self._session_factory() as session:
            rows = session.scalars(document_events_by_ids(event_ids)).all()
            return [_event_from_row(row) for row in rows]


def _snapshot_to_row(snapshot: RawSnapshot) -> RawSnapshotRow:
    """Map a ``RawSnapshot`` domain model to a ``RawSnapshotRow``.

    Args:
        snapshot: RawSnapshot: .

    Returns:
        RawSnapshotRow: .
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
        row: RawSnapshotRow: .

    Returns:
        RawSnapshot: .
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
        event: DocumentEvent: .

    Returns:
        DocumentEventRow: .
    """
    return DocumentEventRow(
        event_id=event.event_id,
        document_id=event.document_id,
        source_url=_postgres_text(event.source_url),
        source_name=_postgres_text(event.source_name),
        source_level=int(event.source_level),
        title=_postgres_text(event.title),
        content=_postgres_text(event.content),
        content_hash=event.content_hash,
        snapshot_id=event.snapshot_id,
        snapshot_hash=event.snapshot_hash,
        symbols=list(event.symbols),
        doc_type=_postgres_text(event.doc_type),
        published_at=event.published_at,
        available_at=event.available_at,
        retrieved_at=event.retrieved_at,
        processing_status=event.processing_status.value,
        processing_error=_postgres_text(event.processing_error),
        is_original=event.is_original,
        duplicate_of=event.duplicate_of,
    )


def _event_from_row(row: DocumentEventRow) -> DocumentEvent:
    """Map a ``DocumentEventRow`` to a ``DocumentEvent`` domain model.

    Args:
        row: DocumentEventRow: .

    Returns:
        DocumentEvent: .
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


def _postgres_text(value: str | None) -> str | None:
    """Return text safe for PostgreSQL text/varchar columns.

    Args:
        value: str | None: .

    Returns:
        str | None: .
    """
    if value is None:
        return None
    return value.replace("\x00", "")


def _search_query_to_row(record: SearchQueryRecord) -> SearchQueryRow:
    """Map a ``SearchQueryRecord`` to a ``SearchQueryRow``.

    Args:
        record: SearchQueryRecord: .

    Returns:
        SearchQueryRow: .
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
        query_id: str: .
        index: int: .
        result: SearchResult: .

    Returns:
        SearchResultRow: .
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
        row: SearchResultRow: .

    Returns:
        SearchResult: .
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
        row: DedupRecordRow: .

    Returns:
        DedupRecord: .
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
        row: RepostEdgeRow: .

    Returns:
        RepostEdge: .
    """
    return RepostEdge(
        parent_event_id=row.parent_event_id,
        child_event_id=row.child_event_id,
        reason=row.reason,
        created_at=row.created_at,
    )


def _news_refresh_run_from_row(row: NewsRefreshRunRow) -> NewsRefreshRun:
    """Map a news refresh run row to its domain summary.

    Args:
        row: NewsRefreshRunRow: .

    Returns:
        NewsRefreshRun: .
    """
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
    """Map a refresh target row to a domain target preserving current queue state.

    Args:
        row: NewsRefreshTargetRow: .

    Returns:
        NewsTarget: .
    """
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
    """Map a materiality score domain object to an ORM row.

    Args:
        score: DocumentMaterialityScore: .

    Returns:
        DocumentMaterialityScoreRow: .
    """
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


def _news_agent_run_to_row(run: NewsAgentRun) -> NewsAgentRunRow:
    """Map an agentic run domain object to a row.

    Args:
        run: NewsAgentRun: .

    Returns:
        NewsAgentRunRow: .
    """
    return NewsAgentRunRow(
        run_id=run.run_id,
        scope_version_id=run.scope_version_id,
        quant_run_id=run.quant_run_id,
        decision_at=run.decision_at,
        status=run.status.value,
        target_count=run.target_count,
        include_near_threshold=run.include_near_threshold,
        config_hash=run.config_hash,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_summary=run.error_summary,
    )


def _news_agent_run_from_row(row: NewsAgentRunRow) -> NewsAgentRun:
    """Map an agentic run row to its domain object.

    Args:
        row: NewsAgentRunRow: .

    Returns:
        NewsAgentRun: .
    """
    return NewsAgentRun(
        run_id=row.run_id,
        scope_version_id=row.scope_version_id,
        quant_run_id=row.quant_run_id,
        decision_at=row.decision_at,
        status=NewsAgentRunStatus(row.status),
        target_count=row.target_count,
        include_near_threshold=row.include_near_threshold,
        config_hash=row.config_hash,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_summary=row.error_summary or {},
    )


def _news_agent_task_to_row(task: NewsAgentTask) -> NewsAgentTaskRow:
    """Map an agentic task domain object to a row.

    Args:
        task: NewsAgentTask: .

    Returns:
        NewsAgentTaskRow: .
    """
    return NewsAgentTaskRow(
        task_id=task.task_id,
        run_id=task.run_id,
        security_id=task.security_id,
        task_type=task.task_type,
        status=task.status.value,
        attempt=task.attempt,
        prompt_version=task.prompt_version,
        prompt_hash=task.prompt_hash,
        schema_hash=task.schema_hash,
        request_hash=task.request_hash,
        response_hash=task.response_hash,
        error_code=task.error_code,
        error_message=task.error_message,
        payload=task.payload,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def _news_agent_task_from_row(row: NewsAgentTaskRow) -> NewsAgentTask:
    """Map an agentic task row to its domain object.

    Args:
        row: NewsAgentTaskRow: .

    Returns:
        NewsAgentTask: .
    """
    return NewsAgentTask(
        task_id=row.task_id,
        run_id=row.run_id,
        security_id=row.security_id,
        task_type=row.task_type,
        status=row.status,
        attempt=row.attempt,
        prompt_version=row.prompt_version,
        prompt_hash=row.prompt_hash,
        schema_hash=row.schema_hash,
        request_hash=row.request_hash,
        response_hash=row.response_hash,
        error_code=row.error_code,
        error_message=row.error_message,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _news_search_plan_to_row(plan: NewsSearchPlan) -> NewsSearchPlanRow:
    """Map a search plan domain object to a row.

    Args:
        plan: NewsSearchPlan: .

    Returns:
        NewsSearchPlanRow: .
    """
    return NewsSearchPlanRow(
        plan_id=plan.plan_id,
        run_id=plan.run_id,
        security_id=plan.security_id,
        symbol=plan.symbol,
        name=plan.name,
        queries=list(plan.queries),
        review_status=plan.review_status,
        fallback_used=plan.fallback_used,
        prompt_version=plan.prompt_version,
        prompt_hash=plan.prompt_hash,
        response_hash=plan.response_hash,
        created_at=plan.created_at,
    )


def _news_search_plan_from_row(row: NewsSearchPlanRow) -> NewsSearchPlan:
    """Map a search plan row to a domain object.

    Args:
        row: NewsSearchPlanRow: .

    Returns:
        NewsSearchPlan: .
    """
    return NewsSearchPlan(
        plan_id=row.plan_id,
        run_id=row.run_id,
        security_id=row.security_id,
        symbol=row.symbol,
        name=row.name,
        queries=tuple(row.queries),
        review_status=row.review_status,
        fallback_used=row.fallback_used,
        prompt_version=row.prompt_version,
        prompt_hash=row.prompt_hash,
        response_hash=row.response_hash,
        created_at=row.created_at,
    )


def _news_article_finding_to_row(
    finding: NewsArticleFinding,
) -> NewsArticleFindingRow:
    """Map an article finding domain object to a row.

    Args:
        finding: NewsArticleFinding: .

    Returns:
        NewsArticleFindingRow: .
    """
    return NewsArticleFindingRow(
        finding_id=finding.finding_id,
        run_id=finding.run_id,
        security_id=finding.security_id,
        event_id=finding.event_id,
        title=finding.title,
        source_url=finding.source_url,
        key_points=list(finding.key_points),
        materiality=finding.materiality,
        sentiment=finding.sentiment,
        risk_flags=list(finding.risk_flags),
        cited_spans=list(finding.cited_spans),
        review_status=finding.review_status,
        confidence=finding.confidence,
        prompt_version=finding.prompt_version,
        prompt_hash=finding.prompt_hash,
        response_hash=finding.response_hash,
        created_at=finding.created_at,
    )


def _news_article_finding_from_row(
    row: NewsArticleFindingRow,
) -> NewsArticleFinding:
    """Map an article finding row to a domain object.

    Args:
        row: NewsArticleFindingRow: .

    Returns:
        NewsArticleFinding: .
    """
    return NewsArticleFinding(
        finding_id=row.finding_id,
        run_id=row.run_id,
        security_id=row.security_id,
        event_id=row.event_id,
        title=row.title,
        source_url=row.source_url,
        key_points=tuple(row.key_points),
        materiality=row.materiality,
        sentiment=row.sentiment,
        risk_flags=tuple(row.risk_flags),
        cited_spans=tuple(row.cited_spans),
        review_status=row.review_status,
        confidence=row.confidence,
        prompt_version=row.prompt_version,
        prompt_hash=row.prompt_hash,
        response_hash=row.response_hash,
        created_at=row.created_at,
    )


def _news_security_brief_to_row(brief: NewsSecurityBrief) -> NewsSecurityBriefRow:
    """Map a security brief domain object to a row.

    Args:
        brief: NewsSecurityBrief: .

    Returns:
        NewsSecurityBriefRow: .
    """
    return NewsSecurityBriefRow(
        brief_id=brief.brief_id,
        run_id=brief.run_id,
        security_id=brief.security_id,
        summary=brief.summary,
        finding_ids=list(brief.finding_ids),
        source_event_ids=list(brief.source_event_ids),
        is_derived=brief.is_derived,
        trust_level=brief.trust_level,
        prompt_version=brief.prompt_version,
        prompt_hash=brief.prompt_hash,
        response_hash=brief.response_hash,
        created_at=brief.created_at,
    )


def _news_security_brief_from_row(row: NewsSecurityBriefRow) -> NewsSecurityBrief:
    """Map a security brief row to a domain object.

    Args:
        row: NewsSecurityBriefRow: .

    Returns:
        NewsSecurityBrief: .
    """
    return NewsSecurityBrief(
        brief_id=row.brief_id,
        run_id=row.run_id,
        security_id=row.security_id,
        summary=row.summary,
        finding_ids=tuple(row.finding_ids),
        source_event_ids=tuple(row.source_event_ids),
        is_derived=row.is_derived,
        trust_level=row.trust_level,
        prompt_version=row.prompt_version,
        prompt_hash=row.prompt_hash,
        response_hash=row.response_hash,
        created_at=row.created_at,
    )
