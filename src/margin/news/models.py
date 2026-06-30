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

import hashlib
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
    """Return the current timezone-aware UTC timestamp.

    Returns:
        Timezone-aware datetime in UTC.
    """
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC, assuming UTC for naive values.

    Args:
        value: Datetime value to normalize.

    Returns:
        Timezone-aware UTC datetime.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# v0.2 news refresh target queue
# ---------------------------------------------------------------------------


class NewsRefreshStatus(StrEnum):
    """Durable status for a target-driven news refresh run.

    Attributes:
        PENDING: Run has been created but not yet started.
        RUNNING: Run is actively processing targets.
        WAITING_RATE_LIMIT: Run is waiting for a provider rate limit to reset.
        WAITING_BUDGET: Run is waiting for a provider budget to reset.
        COMPLETED: All targets processed successfully.
        PARTIAL: Some targets failed but the run completed.
        FAILED: Run failed before completing.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    WAITING_BUDGET = "waiting_budget"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"

    @staticmethod
    def is_terminal_counts(
        *,
        target_count: int,
        completed_count: int,
        failed_final_count: int,
    ) -> bool:
        """Return whether all persisted targets reached a terminal target state.

        Args:
            target_count: Total number of targets in the run.
            completed_count: Number of targets that completed successfully.
            failed_final_count: Number of targets that failed terminally.

        Returns:
            True if the sum of completed and failed-final targets equals the total target
            count.
        """
        return target_count == completed_count + failed_final_count


class NewsTargetStatus(StrEnum):
    """Durable processing state for one research target in a news refresh run.

    Attributes:
        PENDING: Target is waiting to be claimed.
        CLAIMED: Target has been claimed by a worker.
        COMPLETED: Target has been processed successfully.
        RETRY: Target failed and is scheduled for retry.
        FAILED_FINAL: Target has failed terminally after exhausting retries.
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED_FINAL = "failed_final"


class TargetTriggerType(StrEnum):
    """Why a security entered the news refresh target set.

    Attributes:
        QUANT_PASS: Security passed the quant screening.
        MATERIAL_FILING: A material filing was detected for the security.
        THESIS_INVALIDATION_RISK: The investment thesis may be invalidated.
        REVIEW_DUE: The security is due for a periodic review.
        NEW_PASS: Security newly passed the quant screening.
        NEAR_THRESHOLD: Security is near the quant screening threshold.
    """

    QUANT_PASS = "quant_pass"
    MATERIAL_FILING = "material_filing"
    THESIS_INVALIDATION_RISK = "thesis_invalidation_risk"
    REVIEW_DUE = "review_due"
    NEW_PASS = "new_pass"
    NEAR_THRESHOLD = "near_threshold"


class NewsTarget(BaseModel):
    """One complete target that must be searched before a refresh run can reconcile.

    Attributes:
        scope_version_id: Identifier of the scope version that produced the quant run.
        quant_run_id: Identifier of the quant run.
        security_id: Identifier of the target security.
        symbol: Ticker symbol of the target security.
        name: Display name of the target security.
        trigger_type: Why the security entered the target set.
        decision_at: Decision timestamp used to scope the quant run.
        priority: Numeric priority used for claim ordering.
        status: Current durable processing state of the target.
        attempts: Number of processing attempts made.
        next_attempt_at: Scheduled time for the next retry, if any.
        last_error_code: Stable error code from the last failure, if any.
        aliases: Tuple of alternative names for the security.
        industry_terms: Tuple of industry-specific terms for query generation.
    """

    scope_version_id: str
    quant_run_id: str
    security_id: str
    symbol: str
    name: str
    trigger_type: TargetTriggerType
    decision_at: datetime
    priority: int
    status: NewsTargetStatus = NewsTargetStatus.PENDING
    attempts: int = 0
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    industry_terms: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("decision_at", "next_attempt_at")
    @classmethod
    def normalize_target_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize queue timestamps to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime, or None if the input is None.
        """
        if value is None:
            return None
        return ensure_utc(value)

    @property
    def dedupe_key(self) -> str:
        """Stable target key independent of worker attempts or batching.

        Returns:
            SHA-256 hex digest string derived from scope, quant run, security, trigger, and
            decision date.
        """
        payload = "|".join(
            [
                self.scope_version_id,
                self.quant_run_id,
                self.security_id,
                self.trigger_type.value,
                self.decision_at.date().isoformat(),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NewsRefreshRun(BaseModel):
    """Auditable summary of a target-driven news refresh run.

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

    run_id: str
    scope_version_id: str
    quant_run_id: str
    decision_at: datetime
    status: NewsRefreshStatus = NewsRefreshStatus.PENDING
    target_count: int = 0
    completed_count: int = 0
    failed_final_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_at", "created_at", "started_at", "finished_at")
    @classmethod
    def normalize_run_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize run timestamps to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime, or None if the input is None.
        """
        if value is None:
            return None
        return ensure_utc(value)


class NewsTargetWorkItem(BaseModel):
    """Claimed target work item returned by the durable queue.

    Attributes:
        target_id: Unique identifier for the target.
        run_id: Identifier of the parent refresh run.
        target: The claimed ``NewsTarget`` with current queue state.
        claimed_at: Timestamp when the target was claimed.
    """

    target_id: str
    run_id: str
    target: NewsTarget
    claimed_at: datetime

    @field_validator("claimed_at")
    @classmethod
    def normalize_claimed_at(cls, value: datetime) -> datetime:
        """Normalize claim timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class TargetReconciliation(BaseModel):
    """Current target counts for a refresh run.

    Attributes:
        target_count: Total number of targets in the run.
        pending_count: Number of targets waiting to be claimed.
        claimed_count: Number of targets currently claimed by workers.
        retry_count: Number of targets scheduled for retry.
        completed_count: Number of targets that completed successfully.
        failed_final_count: Number of targets that failed terminally.
        is_terminal: Whether all targets have reached a terminal state.
    """

    target_count: int
    pending_count: int
    claimed_count: int
    retry_count: int
    completed_count: int
    failed_final_count: int
    is_terminal: bool

    model_config = {"frozen": True}


class DocumentSecurityLink(BaseModel):
    """Structured relation between a document event and a security.

    Attributes:
        event_id: Identifier of the document event.
        security_id: Identifier of the related security.
        symbol: Ticker symbol of the related security.
        relation_type: Type of relation (e.g., mentioned, targeted_search).
        source: Source of the link (e.g., deterministic_mapper, news_refresh).
        created_at: Timestamp when the link was created.
    """

    event_id: str
    security_id: str
    symbol: str
    relation_type: str = "mentioned"
    source: str = "deterministic_mapper"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_link_created_at(cls, value: datetime) -> datetime:
        """Normalize link timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class DocumentMaterialityScore(BaseModel):
    """Deterministic materiality score for one event/security pair.

    Attributes:
        event_id: Identifier of the document event, if available.
        security_id: Identifier of the security the score applies to.
        relevance_score: Relevance score in the range [0, 1].
        materiality_score: Materiality score in the range [0, 1].
        novelty_score: Novelty score in the range [0, 1].
        trigger_type: Semantic trigger type (e.g., regulatory_penalty, major_contract).
        risk_polarity: Risk polarity (positive, negative, neutral).
        is_material: Whether the document is material enough to influence research.
        reason_codes: Tuple of reason codes supporting the score.
        scoring_version: Version of the scoring rules used.
        is_untrusted_external_text: Whether the source is untrusted external text (L4/L5).
        can_directly_change_research_state: Whether the score may directly change research
            state.
        created_at: Timestamp when the score was created.
    """

    event_id: str | None = None
    security_id: str
    relevance_score: float
    materiality_score: float
    novelty_score: float
    trigger_type: str
    risk_polarity: str
    is_material: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    scoring_version: str
    is_untrusted_external_text: bool
    can_directly_change_research_state: bool
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_score_created_at(cls, value: datetime) -> datetime:
        """Normalize score timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsContextDocument(BaseModel):
    """One selected document in a downstream news context bundle.

    Attributes:
        event_id: Identifier of the document event.
        title: Document title.
        source_level: Source level of the document.
        materiality_score: Materiality score of the document.
        novelty_score: Novelty score of the document.
        published_at: Publication timestamp of the document.
        rank: Zero-based rank of the document within the bundle.
        selection_reason: Reason the document was selected for the bundle.
    """

    event_id: str
    title: str
    source_level: SourceLevel
    materiality_score: float
    novelty_score: float
    published_at: datetime
    rank: int = 0
    selection_reason: str = "materiality_rank"

    @field_validator("published_at")
    @classmethod
    def normalize_context_document_published_at(cls, value: datetime) -> datetime:
        """Normalize publication timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsContextBundle(BaseModel):
    """Bundle of news context passed to RAG/AI with target-completion semantics.

    Attributes:
        bundle_id: Unique identifier for the bundle.
        run_id: Identifier of the parent refresh run.
        security_id: Identifier of the security the bundle covers.
        target_completion_state: Completion state of the target set (complete, partial,
            failed).
        can_support_verified_carry_forward: Whether the bundle can support verified
            carry-forward.
        incomplete_reason_codes: Tuple of reason codes when the bundle is incomplete.
        documents: Tuple of selected ``NewsContextDocument`` objects.
        created_at: Timestamp when the bundle was created.
    """

    bundle_id: str
    run_id: str
    security_id: str
    target_completion_state: str
    can_support_verified_carry_forward: bool
    incomplete_reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    documents: tuple[NewsContextDocument, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_bundle_created_at(cls, value: datetime) -> datetime:
        """Normalize bundle timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


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
