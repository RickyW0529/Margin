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


class ReportFormat(StrEnum):
    """Supported report/export formats for dashboard research items."""

    MARKDOWN = "markdown"
    JSON = "json"


class ResearchRun(BaseModel):
    """A run-level immutable aggregate for module 08 dashboard queries."""

    run_id: str = Field(default_factory=lambda: f"dr_{uuid.uuid4().hex[:12]}")
    decision_at: datetime
    strategy_id: str
    version_id: str
    portfolio_id: str | None = None
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
    counter_arguments: list[str] = Field(default_factory=list)
    portfolio_constraint_violations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value


class EvidenceLocator(BaseModel):
    """Dashboard-friendly evidence locator."""

    evidence_id: str
    source_level: str = "unknown"
    source_url: str | None = None
    content: str = ""
    page: int | None = None
    section: str | None = None

    model_config = {"frozen": True}


class ClaimView(BaseModel):
    """Claim rendered in the evidence panel."""

    claim_id: str
    statement: str
    fact_or_inference: str = "unknown"
    confidence: float = 0.0
    has_conflict: bool = False
    evidence_ids: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class EvidenceView(BaseModel):
    """Expanded evidence view for a research item."""

    item_id: str
    claims: list[ClaimView] = Field(default_factory=list)
    evidence_by_level: dict[str, list[EvidenceLocator]] = Field(default_factory=dict)
    source_distribution: dict[str, int] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    locators_available: bool = False

    model_config = {"frozen": True}


class ValuationView(BaseModel):
    """Valuation view for a research item."""

    item_id: str
    base_valuation_range: tuple[float, float] | None = None
    pessimistic_range: tuple[float, float] | None = None
    margin_of_safety: float | None = None
    value_trap_score: float | None = None
    method: str | None = None
    notes: str = ""

    model_config = {"frozen": True}


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
        return ensure_utc(value)


class CandidateCard(BaseModel):
    """Derived candidate card used by the research dashboard UI."""

    item_id: str
    run_id: str
    symbol: str
    signal_type: str = ""
    confidence: float = 0.0
    statement: str = ""
    current_price: float | None = None
    quantitative_rank: int | None = None
    research_status: str = ""
    position_review_status: str | None = None
    valuation_range: tuple[float, float] | None = None
    margin_of_safety: float | None = None
    value_trap_score: float | None = None
    event_window: str | None = None
    catalysts: list[str] = Field(default_factory=list)
    counter_arguments: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    watch_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    strategy_version: str = ""
    disclaimer: str = "本系统输出研究分析，不构成买卖指令。"

    model_config = {"frozen": True}


class HomeSummary(BaseModel):
    """Six-block home summary for the research candidate dashboard."""

    decision_at: datetime | None = None
    run_id: str | None = None
    strategy_id: str | None = None
    version_id: str | None = None
    run_status: str | None = None
    today_candidates: list[CandidateCard] = Field(default_factory=list)
    position_reviews: list[CandidateCard] = Field(default_factory=list)
    high_priority_risks: list[CandidateCard] = Field(default_factory=list)
    rejections: list[CandidateCard] = Field(default_factory=list)
    run_stats: dict[str, int] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ProviderStatus(BaseModel):
    """Health metadata for a dashboard-facing provider or subsystem."""

    provider: str
    status: str
    message: str = ""

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
        return ensure_utc(value)


class AuditView(BaseModel):
    """Audit trace for a research dashboard item."""

    item_id: str
    workflow_run_id: str
    snapshot_id: str | None = None
    workflow_state: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    trace_count: int = 0
    tool_call_ids: list[str] = Field(default_factory=list)
    error: str | None = None

    model_config = {"frozen": True}


class ResearchReport(BaseModel):
    """Rendered research report for a dashboard item."""

    item_id: str
    run_id: str
    symbol: str
    title: str
    format: ReportFormat = ReportFormat.MARKDOWN
    content: str
    sections: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ReportExport(BaseModel):
    """Export payload for a rendered dashboard research report."""

    item_id: str
    format: ReportFormat
    filename: str
    mime_type: str
    content: str
    generated_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)
