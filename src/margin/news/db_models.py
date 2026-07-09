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
    """Restart-safe incremental cursor per source stream.."""

    __tablename__ = "source_cursors"

    source_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsRefreshRunRow(Base):
    """Durable target-driven news refresh run.."""

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
    """One persisted research target in a news refresh run.."""

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
    """Immutable raw downloaded content snapshot metadata.."""

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
    """Persisted normalized document event.."""

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
    """Transactional outbox row for document event consumers.."""

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
    """Immutable web search query audit record.."""

    __tablename__ = "search_queries"

    query_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    api_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)


class SearchResultRow(Base):
    """Persisted raw WebSearch result.."""

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
    """Persisted duplicate decision.."""

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
    """Canonical repost chain edge.."""

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
    """Many-to-many security relation for a document event.."""

    __tablename__ = "document_security_links"
    __table_args__ = (Index("ix_document_security_links_security", "security_id", "event_id"),)

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
    """Deterministic materiality score per document/security/scoring version.."""

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
    """Persisted context bundle handed to RAG/AI modules.."""

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
    """Ordered document membership for a news context bundle.."""

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
    """Top-level agentic news acquisition run.."""

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
    """One agentic LLM/deterministic task audit row.."""

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
    """Reviewed security-level WebSearch query plan.."""

    __tablename__ = "news_search_plans"
    __table_args__ = (Index("ix_news_search_plans_run_security", "run_id", "security_id"),)

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
    """Reviewed article-level finding extracted from one document event.."""

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
    """Derived security-level news brief.."""

    __tablename__ = "news_security_briefs"
    __table_args__ = (Index("ix_news_security_briefs_run_security", "run_id", "security_id"),)

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
