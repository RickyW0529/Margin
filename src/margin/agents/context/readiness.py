"""Data readiness models for Agent ContextPacks."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReadinessStatus(StrEnum):
    """Readiness state for one context/data source."""

    READY = "ready"
    EMPTY = "empty"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    PERMISSION_DENIED = "permission_denied"
    ERROR = "error"
    UNKNOWN = "unknown"


class SourceReadiness(BaseModel):
    """Readiness status for one source used by Agent planning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_name: str
    status: ReadinessStatus
    as_of: datetime | None = None
    latest_run_id: str | None = None
    latest_artifact_refs: tuple[str, ...] = ()
    row_count: int | None = None
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    retryable: bool = False
    safe_summary: str


class DataReadinessArtifactPayload(BaseModel):
    """Payload stored in a data_readiness context artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    user_goal: str
    scope_version_id: str
    generated_at: datetime
    sources: tuple[SourceReadiness, ...]
    missing_for_goal: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()


class CandidateLoadResult(BaseModel):
    """Typed dashboard candidate load result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReadinessStatus
    rows: tuple[dict[str, Any], ...] = ()
    latest_run_id: str | None = None
    as_of: datetime | None = None
    error_code: str | None = None
    retryable: bool = False
    safe_summary: str = ""
