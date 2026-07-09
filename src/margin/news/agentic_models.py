"""Domain models for agentic news acquisition artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class NewsAgentRunStatus(StrEnum):
    """Durable status for one agentic news acquisition run.."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_EMPTY = "completed_empty"
    WAITING_PROVIDER = "waiting_provider"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    PARTIAL = "partial"
    FAILED = "failed"


class NewsAgentTaskStatus(StrEnum):
    """Durable status for one agentic node/task.."""

    PENDING = "pending"
    RUNNING = "running"
    APPROVED = "approved"
    FALLBACK = "fallback"
    RETRY = "retry"
    FAILED_FINAL = "failed_final"


class NewsAgentRun(BaseModel):
    """Auditable top-level agentic news acquisition run.."""

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
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        if value is None:
            return None
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsAgentTask(BaseModel):
    """One persisted LLM or deterministic task in the agentic pipeline.."""

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
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        if value is None:
            return None
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsSearchPlan(BaseModel):
    """Reviewed query plan for one security target.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsArticleFinding(BaseModel):
    """Reviewed article-level finding extracted from a persisted document event.."""

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
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}


class NewsSecurityBrief(BaseModel):
    """Derived security-level news brief assembled from approved findings.."""

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
        """Normalize timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    model_config = {"frozen": True}
