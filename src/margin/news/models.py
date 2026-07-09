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
    """Source priority level from L1 (highest) to L5 (lowest).."""

    L1 = 1  # Exchange announcements, regulatory filings, and periodic reports.
    L2 = 2  # Official IR channels, earnings calls, and formal management guidance.
    L3 = 3  # Hard industry data such as prices, sales volumes, inventory, and tenders.
    L4 = 4  # Authoritative media and professional research.
    L5 = 5  # Social media and unverified sources.


class DocumentStatus(StrEnum):
    """Processing status controlling whether a document may be used as evidence.."""

    READY = "ready"
    PARSE_FAILED = "parse_failed"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp.

    Returns:
        datetime: .
    """
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC, assuming UTC for naive values.

    Args:
        value: datetime: .

    Returns:
        datetime: .
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# v0.2 news refresh target queue
# ---------------------------------------------------------------------------


class NewsRefreshStatus(StrEnum):
    """Durable status for a target-driven news refresh run.."""

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
            target_count: int: .
            completed_count: int: .
            failed_final_count: int: .

        Returns:
            bool: .
        """
        return target_count == completed_count + failed_final_count


class NewsTargetStatus(StrEnum):
    """Durable processing state for one research target in a news refresh run.."""

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED_FINAL = "failed_final"


class TargetTriggerType(StrEnum):
    """Why a security entered the news refresh target set.."""

    QUANT_PASS = "quant_pass"
    MATERIAL_FILING = "material_filing"
    THESIS_INVALIDATION_RISK = "thesis_invalidation_risk"
    REVIEW_DUE = "review_due"
    NEW_PASS = "new_pass"
    NEAR_THRESHOLD = "near_threshold"


class NewsTarget(BaseModel):
    """One complete target that must be searched before a refresh run can reconcile.."""

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
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        if value is None:
            return None
        return ensure_utc(value)

    @property
    def dedupe_key(self) -> str:
        """Stable target key independent of worker attempts or batching.

        Returns:
            str: .
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
    """Auditable summary of a target-driven news refresh run.."""

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
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        if value is None:
            return None
        return ensure_utc(value)


class NewsTargetWorkItem(BaseModel):
    """Claimed target work item returned by the durable queue.."""

    target_id: str
    run_id: str
    target: NewsTarget
    claimed_at: datetime

    @field_validator("claimed_at")
    @classmethod
    def normalize_claimed_at(cls, value: datetime) -> datetime:
        """Normalize claim timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class TargetReconciliation(BaseModel):
    """Current target counts for a refresh run.."""

    target_count: int
    pending_count: int
    claimed_count: int
    retry_count: int
    completed_count: int
    failed_final_count: int
    is_terminal: bool

    model_config = {"frozen": True}


class DocumentSecurityLink(BaseModel):
    """Structured relation between a document event and a security.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class DocumentMaterialityScore(BaseModel):
    """Deterministic materiality score for one event/security pair.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsContextDocument(BaseModel):
    """One selected document in a downstream news context bundle.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsContextBundle(BaseModel):
    """Bundle of news context passed to RAG/AI with target-completion semantics.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Raw snapshot
# ---------------------------------------------------------------------------


class RawSnapshot(BaseModel):
    """Immutable snapshot of downloaded original content.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


# ---------------------------------------------------------------------------
# Normalized document event
# ---------------------------------------------------------------------------


class DocumentEvent(BaseModel):
    """Normalized document event published after acquisition and enrichment.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    @property
    def can_change_research_state(self) -> bool:
        """Whether this source level is allowed to directly change research or portfolio state.

        Returns:
            bool: .
        """
        return (
            self.processing_status == DocumentStatus.READY and self.source_level <= SourceLevel.L3
        )


# ---------------------------------------------------------------------------
# Source descriptor
# ---------------------------------------------------------------------------


class SourceDescriptor(BaseModel):
    """Registered source descriptor used by the source registry.."""

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
        content: str | bytes: .

    Returns:
        str: .
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
        source_url: str: .
        source_name: str: .
        source_level: SourceLevel: .
        title: str: .
        content: str | None: .
        content_hash: str | None: .
        symbols: list[str] | None: .
        doc_type: str: .
        published_at: datetime | None: .
        available_at: datetime | None: .
        snapshot_id: str | None: .
        snapshot_hash: str | None: .
        processing_status: DocumentStatus: .
        processing_error: str | None: .

    Returns:
        DocumentEvent: .
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
