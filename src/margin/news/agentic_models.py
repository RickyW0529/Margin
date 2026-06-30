"""Domain models for agentic news acquisition artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class NewsAgentRunStatus(StrEnum):
    """Durable status for one agentic news acquisition run.

    Attributes:
        PENDING: Run has been created but not yet started.
        RUNNING: Run is actively processing targets.
        COMPLETED: All targets processed successfully.
        COMPLETED_EMPTY: Run completed with no eligible targets.
        WAITING_PROVIDER: Run is waiting for a provider to become available.
        WAITING_RATE_LIMIT: Run is waiting for a provider rate limit to reset.
        PARTIAL: Some targets failed but the run completed.
        FAILED: Run failed before completing.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_EMPTY = "completed_empty"
    WAITING_PROVIDER = "waiting_provider"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    PARTIAL = "partial"
    FAILED = "failed"


class NewsAgentTaskStatus(StrEnum):
    """Durable status for one agentic node/task.

    Attributes:
        PENDING: Task has been created but not yet started.
        RUNNING: Task is actively executing.
        APPROVED: Task output was reviewed and approved.
        FALLBACK: Task used a deterministic fallback instead of LLM output.
        RETRY: Task is scheduled for retry after a failure.
        FAILED_FINAL: Task has failed terminally after exhausting retries.
    """

    PENDING = "pending"
    RUNNING = "running"
    APPROVED = "approved"
    FALLBACK = "fallback"
    RETRY = "retry"
    FAILED_FINAL = "failed_final"


class NewsAgentRun(BaseModel):
    """Auditable top-level agentic news acquisition run.

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

    run_id: str
    scope_version_id: str
    quant_run_id: str
    decision_at: datetime
    status: NewsAgentRunStatus = NewsAgentRunStatus.PENDING
    target_count: int = 0
    include_near_threshold: bool = False
    config_hash: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_at", "created_at", "started_at", "finished_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        """Normalize timestamps to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime, or None if the input is None.
        """
        if value is None:
            return None
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsAgentTask(BaseModel):
    """One persisted LLM or deterministic task in the agentic pipeline.

    Attributes:
        task_id: Unique identifier for the task.
        run_id: Identifier of the parent agentic run.
        security_id: Identifier of the security the task operates on, if any.
        task_type: Semantic type of the task (e.g., keyword_writer, article_writer).
        status: Current durable status of the task.
        attempt: Zero-based attempt number for retry tracking.
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

    task_id: str
    run_id: str
    security_id: str | None = None
    task_type: str
    status: NewsAgentTaskStatus = NewsAgentTaskStatus.PENDING
    attempt: int = 0
    prompt_version: str = ""
    prompt_hash: str = ""
    schema_hash: str = ""
    request_hash: str = ""
    response_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("created_at", "completed_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        """Normalize timestamps to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime, or None if the input is None.
        """
        if value is None:
            return None
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsSearchPlan(BaseModel):
    """Reviewed query plan for one security target.

    Attributes:
        plan_id: Unique identifier for the plan.
        run_id: Identifier of the parent agentic run.
        security_id: Identifier of the security the plan targets.
        symbol: Ticker symbol of the target security.
        name: Display name of the target security.
        queries: Tuple of WebSearch query strings.
        review_status: Review outcome (approved or fallback).
        fallback_used: Whether a deterministic fallback was used instead of LLM output.
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the plan was created.
    """

    plan_id: str
    run_id: str
    security_id: str
    symbol: str
    name: str
    queries: tuple[str, ...] = Field(default_factory=tuple)
    review_status: str
    fallback_used: bool = False
    prompt_version: str = ""
    prompt_hash: str = ""
    response_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsArticleFinding(BaseModel):
    """Reviewed article-level finding extracted from a persisted document event.

    Attributes:
        finding_id: Unique identifier for the finding.
        run_id: Identifier of the parent agentic run.
        security_id: Identifier of the security the finding relates to.
        event_id: Identifier of the source document event.
        title: Title of the source document.
        source_url: URL of the source document.
        key_points: Tuple of evidence-bound key points extracted from the article.
        materiality: Materiality classification, if any.
        sentiment: Sentiment classification, if any.
        risk_flags: Tuple of risk flag strings.
        cited_spans: Tuple of cited source span dictionaries.
        review_status: Review outcome (approved or rejected).
        confidence: Confidence score in the range [0, 1].
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the finding was created.
    """

    finding_id: str
    run_id: str
    security_id: str
    event_id: str
    title: str
    source_url: str
    key_points: tuple[str, ...] = Field(default_factory=tuple)
    materiality: str | None = None
    sentiment: str | None = None
    risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    cited_spans: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    review_status: str
    confidence: float = 0.0
    prompt_version: str = ""
    prompt_hash: str = ""
    response_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize timestamp to UTC.

        Args:
            value: Datetime value provided during model construction.

        Returns:
            Timezone-aware UTC datetime.
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsSecurityBrief(BaseModel):
    """Derived security-level news brief assembled from approved findings.

    Attributes:
        brief_id: Unique identifier for the brief.
        run_id: Identifier of the parent agentic run.
        security_id: Identifier of the security the brief covers.
        summary: Summarized news brief text.
        finding_ids: Tuple of finding identifiers that contributed to the brief.
        source_event_ids: Tuple of source document event identifiers.
        is_derived: Whether the brief is derived (non-primary) rather than from an original
            source.
        trust_level: Trust level label for the brief.
        prompt_version: Version of the prompt template used.
        prompt_hash: Hash of the rendered prompt for audit.
        response_hash: Hash of the LLM response, if any.
        created_at: Timestamp when the brief was created.
    """

    brief_id: str
    run_id: str
    security_id: str
    summary: str
    finding_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = Field(default_factory=tuple)
    is_derived: bool = True
    trust_level: str = "derived_low_trust"
    prompt_version: str = ""
    prompt_hash: str = ""
    response_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize timestamp to UTC."""
        return ensure_utc(value)

    model_config = {"frozen": True}
