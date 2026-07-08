"""Domain models for the research candidate dashboard module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class RunStatus(StrEnum):
    """Terminal state of a dashboard-level batch research run."""

    PUBLISHED = "published"
    ABSTAINED = "abstained"
    ABORTED = "aborted"
    PARTIAL = "partial"


class ItemStatus(StrEnum):
    """Dashboard status for a single research item."""

    PUBLISHED = "published"
    ABSTAINED = "abstained"
    ABORTED = "aborted"
    DATA_MISSING = "data_missing"


class FeedbackType(StrEnum):
    """Allowed user feedback actions for a research item."""

    ACCEPT = "accept"
    REJECT = "reject"
    WATCH = "watch"
    COMMENT = "comment"


class JobStatus(StrEnum):
    """Synchronous MVP job status for nightly dashboard runs."""

    COMPLETED = "completed"
    FAILED = "failed"


class ResearchRun(BaseModel):
    """A run-level immutable aggregate for module 08 dashboard queries."""

    run_id: str = Field(default_factory=lambda: f"dr_{uuid.uuid4().hex[:12]}")
    decision_at: datetime
    strategy_id: str
    version_id: str
    universe: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.PUBLISHED
    summary: str = ""
    item_count: int = 0
    published_count: int = 0
    abstained_count: int = 0
    aborted_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("decision_at", "created_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Normalize timestamp fields to UTC.

        Args:
            value: The datetime value to normalize.

        Returns:
            A timezone-aware UTC datetime.
        """
        return ensure_utc(value)


class ResearchItem(BaseModel):
    """A symbol-level item generated from a module 06 workflow result."""

    item_id: str = Field(default_factory=lambda: f"di_{uuid.uuid4().hex[:12]}")
    run_id: str
    symbol: str
    signal_type: str = ""
    confidence: float = 0.0
    statement: str = ""
    workflow_run_id: str = ""
    snapshot_id: str | None = None
    status: ItemStatus = ItemStatus.PUBLISHED
    abstain_reason: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    risk_score: float | None = None
    target_weight: float | None = None
    adjusted_weight: float | None = None
    agent_adjustment: dict[str, Any] = Field(default_factory=dict)
    counter_arguments: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize the created_at timestamp to UTC.

        Args:
            value: The datetime value to normalize.

        Returns:
            A timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Validate that confidence is within the unit interval.

        Args:
            value: Confidence score to validate.

        Returns:
            The validated confidence score.

        Raises:
            ValueError: If confidence is not between 0.0 and 1.0.
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value


class FeedbackRecord(BaseModel):
    """Append-only user feedback for a research item."""

    feedback_id: str = Field(default_factory=lambda: f"fb_{uuid.uuid4().hex[:12]}")
    item_id: str
    feedback_type: FeedbackType = FeedbackType.COMMENT
    comment: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize the created_at timestamp to UTC.

        Args:
            value: The datetime value to normalize.

        Returns:
            A timezone-aware UTC datetime.
        """
        return ensure_utc(value)


class ProviderStatus(BaseModel):
    """Health metadata for a dashboard-facing provider or subsystem."""

    provider: str
    status: str
    message: str = ""

    model_config = {"frozen": True}


class DashboardPageInfo(BaseModel):
    """Cursor page metadata for v0.2 dashboard BFF responses."""

    next_cursor: str | None = None
    previous_cursor: str | None = None
    has_next_page: bool = False
    page_size: int = 50

    model_config = {"frozen": True}


class DashboardFilters(BaseModel):
    """Server-side filters for v0.2 research candidate queries."""

    screening_status: str | None = None
    data_status: str | None = None
    review_required: bool | None = None
    assessment_freshness: str | None = None
    query: str | None = None

    model_config = {"frozen": True}


class DashboardSort(BaseModel):
    """Safe sort descriptor for v0.2 research candidate queries."""

    field: str = "final_score"
    direction: str = "desc"

    model_config = {"frozen": True}

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str) -> str:
        """Validate sort field."""
        allowed = {"final_score", "confidence", "last_checked_at", "symbol"}
        if value not in allowed:
            raise ValueError(f"unsupported dashboard sort field: {value}")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        """Validate sort direction."""
        normalized = value.lower()
        if normalized not in {"asc", "desc"}:
            raise ValueError(f"unsupported dashboard sort direction: {value}")
        return normalized


class ResearchCandidateListItemV2(BaseModel):
    """One row in the v0.2 all-company research candidate list."""

    item_id: str
    security_id: str
    symbol: str
    name: str
    scope_version_id: str
    screening_status: str
    data_status: str
    risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    review_required: bool = False
    research_guardrail: str = "allow_research"
    current_review_outcome: str | None = None
    effective_assessment_id: str | None = None
    assessment_freshness: str | None = None
    stale_reason: str | None = None
    final_score: float | None = None
    target_weight: float | None = None
    adjusted_weight: float | None = None
    agent_adjustment: dict[str, Any] = Field(default_factory=dict)
    discount_rate: float | None = None
    confidence: float | None = None
    last_checked_at: datetime

    model_config = {"frozen": True}

    @field_validator("last_checked_at")
    @classmethod
    def normalize_last_checked_at(cls, value: datetime) -> datetime:
        """Normalize last checked timestamp."""
        return ensure_utc(value)


class ResearchCandidateListResponse(BaseModel):
    """Paged v0.2 research candidate list response."""

    items: tuple[ResearchCandidateListItemV2, ...] = Field(default_factory=tuple)
    page_info: DashboardPageInfo = Field(default_factory=DashboardPageInfo)
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)
    as_of: datetime = Field(default_factory=utc_now)
    scope_version_id: str

    model_config = {"frozen": True}

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Normalize as_of timestamp."""
        return ensure_utc(value)


class ResearchItemDetailV2(BaseModel):
    """Company detail BFF DTO for the v0.2 dashboard."""

    item: ResearchCandidateListItemV2
    current_review: dict[str, Any] = Field(default_factory=dict)
    effective_assessment: dict[str, Any] = Field(default_factory=dict)
    factors: dict[str, Any] = Field(default_factory=dict)
    thesis: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    versions: dict[str, str] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ProviderSettingsView(BaseModel):
    """Provider settings DTO shown by the dashboard."""

    provider_id: str
    provider_name: str
    configured: bool = False
    last_four: str | None = None
    version_id: str | None = None
    status: str = "inactive"
    health: str | None = None

    model_config = {"frozen": True}


class ScopeSettingsView(BaseModel):
    """Scope settings DTO shown by the dashboard."""

    scope_version_id: str
    universe_code: str
    indicator_view_version_id: str | None = None
    active: bool = False

    model_config = {"frozen": True}


class JobRun(BaseModel):
    """Synchronous MVP job record for nightly run endpoints."""

    job_run_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")
    run_id: str
    status: JobStatus = JobStatus.COMPLETED
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize the created_at timestamp to UTC.

        Args:
            value: The datetime value to normalize.

        Returns:
            A timezone-aware UTC datetime.
        """
        return ensure_utc(value)
