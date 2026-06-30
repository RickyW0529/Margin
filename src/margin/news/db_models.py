"""SQLAlchemy models for news acquisition, search, and dedup persistence.

Maps domain entities such as raw snapshots, document events, web search queries, and dedup
records to PostgreSQL tables. JSONB columns are used for structured fields such as symbol lists.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class NewsRefreshRunRow(Base):
    """Durable target-driven news refresh run.

    Attributes:
        run_id: Unique identifier for the run.
        scope_version_id: Identifier of the scope version that produced the quant run.
        quant_run_id: Identifier of the quant run being refreshed.
        decision_at: Decision timestamp used to scope the quant run.
        status: Current durable status of the run.
        target_count: Total number of targets in the run.
        completed_count: Number of targets that completed successfully.
        failed_final_count: Number of targets that failed terminally.
        created_at: Timestamp when the run was created.
        started_at: Timestamp when the run started processing, if any.
        finished_at: Timestamp when the run finished, if any.
        error_summary: Structured error summary for failed or partial runs.
    """

    __tablename__ = "news_refresh_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quant_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_final_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class NewsRefreshTargetRow(Base):
    """One persisted research target in a news refresh run.

    Attributes:
        target_id: Unique identifier for the target.
        run_id: Foreign key to the parent refresh run.
        dedupe_key: Stable deduplication key for the target.
        security_id: Identifier of the target security.
        symbol: Ticker symbol of the target security.
        name: Display name of the target security.
        trigger_type: Why the security entered the target set.
        priority: Numeric priority used for claim ordering.
        status: Current durable processing state of the target.
        attempts: Number of processing attempts made.
        next_attempt_at: Scheduled time for the next retry, if any.
        last_error_code: Stable error code from the last failure, if any.
        last_error_message: Human-readable error message from the last failure, if any.
        payload: Full target payload as JSON for audit and reconstruction.
        created_at: Timestamp when the target was created.
        claimed_at: Timestamp when the target was last claimed, if any.
        completed_at: Timestamp when the target was completed, if any.
    """

    __tablename__ = "news_refresh_targets"
    __table_args__ = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_news_target_dedupe"),
        Index(
            "ix_news_target_claim",
            "run_id",
            "status",
            "priority",
            "next_attempt_at",
        ),
        Index("ix_news_target_security_run", "security_id", "run_id"),
    )

    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_refresh_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    dedupe_key: Mapped[str] = mapped_column(String(96), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(48), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class DocumentSecurityLinkRow(Base):
    """Many-to-many security relation for a document event.

    Attributes:
        event_id: Foreign key to the document event; part of the primary key.
        security_id: Identifier of the related security; part of the primary key.
        symbol: Ticker symbol of the related security.
        relation_type: Type of relation (e.g., mentioned, targeted_search).
        source: Source of the link (e.g., deterministic_mapper, news_refresh).
        created_at: Timestamp when the link was created.
    """

    __tablename__ = "document_security_links"
    __table_args__ = (
        Index("ix_document_security_links_security", "security_id", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    security_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentMaterialityScoreRow(Base):
    """Deterministic materiality score per document/security/scoring version.

    Attributes:
        score_id: Auto-incrementing primary key.
        event_id: Foreign key to the document event being scored.
        security_id: Identifier of the security the score applies to.
        relevance_score: Relevance score in the range [0, 1].
        materiality_score: Materiality score in the range [0, 1].
        novelty_score: Novelty score in the range [0, 1].
        trigger_type: Semantic trigger type (e.g., regulatory_penalty, major_contract).
        risk_polarity: Risk polarity (positive, negative, neutral).
        is_material: Whether the document is material enough to influence research.
        reason_codes: List of reason codes supporting the score.
        scoring_version: Version of the scoring rules used.
        is_untrusted_external_text: Whether the source is untrusted external text (L4/L5).
        can_directly_change_research_state: Whether the score may directly change research
            state.
        created_at: Timestamp when the score was created.
    """

    __tablename__ = "document_materiality_scores"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "security_id",
            "scoring_version",
            name="uq_document_materiality_version",
        ),
        Index(
            "ix_document_materiality_security",
            "security_id",
            "is_material",
            "materiality_score",
        ),
    )

    score_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    materiality_score: Mapped[float] = mapped_column(Float, nullable=False)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_polarity: Mapped[str] = mapped_column(String(32), nullable=False)
    is_material: Mapped[bool] = mapped_column(nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_untrusted_external_text: Mapped[bool] = mapped_column(nullable=False)
    can_directly_change_research_state: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsContextBundleRow(Base):
    """Persisted context bundle handed to RAG/AI modules.

    Attributes:
        bundle_id: Unique identifier for the bundle.
        run_id: Foreign key to the parent refresh run.
        security_id: Identifier of the security the bundle covers.
        target_completion_state: Completion state of the target set (complete, partial,
            failed).
        can_support_verified_carry_forward: Whether the bundle can support verified
            carry-forward.
        incomplete_reason_codes: List of reason codes when the bundle is incomplete.
        created_at: Timestamp when the bundle was created.
    """

    __tablename__ = "news_context_bundles"

    bundle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_refresh_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    security_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_completion_state: Mapped[str] = mapped_column(String(32), nullable=False)
    can_support_verified_carry_forward: Mapped[bool] = mapped_column(nullable=False)
    incomplete_reason_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsContextDocumentRow(Base):
    """Ordered document membership for a news context bundle.

    Attributes:
        bundle_id: Foreign key to the parent context bundle; part of the primary key.
        event_id: Foreign key to the document event; part of the primary key.
        rank: Zero-based rank of the document within the bundle.
        selection_reason: Reason the document was selected for the bundle.
    """

    __tablename__ = "news_context_documents"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id",
            "event_id",
            name="uq_news_context_document",
        ),
    )

    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("news_context_bundles.bundle_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("document_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_reason: Mapped[str] = mapped_column(Text, nullable=False)


class NewsAgentRunRow(Base):
    """Top-level agentic news acquisition run.

    Attributes:
        run_id: Unique identifier for the run.
        scope_version_id: Identifier of the scope version that produced the quant run.
        quant_run_id: Identifier of the quant run being acquired for.
        decision_at: Decision timestamp used to scope the quant run.
        status: Current durable status of the run.
        target_count: Total number of targets in the run.
        include_near_threshold: Whether near-threshold securities were included.
        config_hash: Stable hash of the run configuration for audit.
        created_at: Timestamp when the run was created.
        started_at: Timestamp when the run started processing, if any.
        finished_at: Timestamp when the run finished, if any.
        error_summary: Structured error summary for failed or partial runs.
    """

    __tablename__ = "news_agent_runs"
    __table_args__ = (
        Index("ix_news_agent_runs_scope_decision", "scope_version_id", "decision_at"),
        Index("ix_news_agent_runs_quant_run", "quant_run_id"),
        Index("ix_news_agent_runs_status", "status"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quant_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    include_near_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class NewsAgentTaskRow(Base):
    """One agentic LLM/deterministic task audit row.

    Attributes:
        task_id: Unique identifier for the task.
        run_id: Foreign key to the parent agentic run.
        security_id: Identifier of the security the task operates on, if any.
        task_type: Semantic type of the task.
        status: Current durable status of the task.
        attempt: Number of attempts made.
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        schema_hash: Hash of the output JSON schema for audit.
        request_hash: Hash of the full request payload for audit.
        response_hash: Hash of the LLM response, if any.
        error_code: Stable error code when the task fails.
        error_message: Human-readable error message when the task fails.
        payload: Structured task-specific payload.
        created_at: Timestamp when the task was created.
        completed_at: Timestamp when the task completed, if any.
    """

    __tablename__ = "news_agent_tasks"
    __table_args__ = (
        Index("ix_news_agent_tasks_run_type", "run_id", "task_type"),
        Index("ix_news_agent_tasks_security", "security_id", "run_id"),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str | None] = mapped_column(String(32))
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_version: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    schema_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    request_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    response_hash: Mapped[str | None] = mapped_column(String(96))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsSearchPlanRow(Base):
    """Reviewed security-level WebSearch query plan.

    Attributes:
        plan_id: Unique identifier for the plan.
        run_id: Foreign key to the parent agentic run.
        security_id: Identifier of the security the plan targets.
        symbol: Ticker symbol of the target security.
        name: Display name of the target security.
        queries: List of WebSearch query strings.
        review_status: Review outcome (approved or fallback).
        fallback_used: Whether a deterministic fallback was used.
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the plan was created.
    """

    __tablename__ = "news_search_plans"
    __table_args__ = (
        Index("ix_news_search_plans_run_security", "run_id", "security_id"),
    )

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    queries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_version: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    response_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsArticleFindingRow(Base):
    """Reviewed article-level finding extracted from one document event.

    Attributes:
        finding_id: Unique identifier for the finding.
        run_id: Foreign key to the parent agentic run.
        security_id: Identifier of the security the finding relates to.
        event_id: Identifier of the source document event.
        title: Title of the source document.
        source_url: URL of the source document.
        key_points: List of evidence-bound key points.
        materiality: Materiality classification, if any.
        sentiment: Sentiment classification, if any.
        risk_flags: List of risk flag strings.
        cited_spans: List of cited source span dictionaries.
        review_status: Review outcome (approved or rejected).
        confidence: Confidence score in the range [0, 1].
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the finding was created.
    """

    __tablename__ = "news_article_findings"
    __table_args__ = (
        Index("ix_news_article_findings_run_security", "run_id", "security_id"),
        Index("ix_news_article_findings_event", "event_id"),
    )

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    materiality: Mapped[str | None] = mapped_column(String(32))
    sentiment: Mapped[str | None] = mapped_column(String(32))
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cited_spans: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    response_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsSecurityBriefRow(Base):
    """Derived security-level news brief.

    Attributes:
        brief_id: Unique identifier for the brief.
        run_id: Foreign key to the parent agentic run.
        security_id: Identifier of the security the brief covers.
        summary: Summarized news brief text.
        finding_ids: List of finding identifiers that contributed to the brief.
        source_event_ids: List of source document event identifiers.
        is_derived: Whether the brief is derived rather than from an original source.
        trust_level: Trust level label for the brief.
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the brief was created.
    """

    __tablename__ = "news_security_briefs"
    __table_args__ = (
        Index("ix_news_security_briefs_run_security", "run_id", "security_id"),
    )

    brief_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("news_agent_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    finding_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_event_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trust_level: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    response_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
