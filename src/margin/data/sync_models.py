"""Pydantic contracts for data sync runs and endpoint work items."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class DataSyncStatus(StrEnum):
    """Run/work-item status values for provider sync."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Return whether no automatic processing remains.

        Returns:
            ``True`` for succeeded, partial, final-failure, and cancelled states.
        """
        return self in {
            DataSyncStatus.SUCCEEDED,
            DataSyncStatus.PARTIAL,
            DataSyncStatus.FAILED_FINAL,
            DataSyncStatus.CANCELLED,
        }


class DataSyncRequest(BaseModel):
    """Request to create a durable provider sync run."""

    provider: str | None = None
    endpoint_codes: tuple[str, ...] = Field(default_factory=tuple)
    requested_by: str = "system"
    backfill_start: datetime | None = None
    backfill_end: datetime | None = None
    force_full_refresh: bool = False
    idempotency_key: str | None = None
    data_policy_version_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None

    model_config = {"frozen": True}

    @field_validator(
        "backfill_start",
        "backfill_end",
        "window_start",
        "window_end",
    )
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        """Normalize optional request timestamps to UTC."""
        return ensure_utc(value) if value is not None else None

    @property
    def input_hash(self) -> str:
        """Return deterministic request hash for idempotency and audit.

        Returns:
            A ``sha256:``-prefixed hex digest of the JSON-serialized request.
        """
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DataSyncRun(BaseModel):
    """Durable sync run summary."""

    run_id: str
    request: DataSyncRequest
    status: DataSyncStatus = DataSyncStatus.PENDING
    endpoint_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("created_at", "started_at", "finished_at")
    @classmethod
    def normalize_run_time(cls, value: datetime | None) -> datetime | None:
        """Normalize run timestamps to UTC."""
        return ensure_utc(value) if value is not None else None


class EndpointWorkItem(BaseModel):
    """Endpoint-level work item created before external provider calls."""

    work_item_id: str
    run_id: str
    provider: str
    endpoint_code: str
    status: DataSyncStatus = DataSyncStatus.PENDING
    cursor_before: str | None = None
    cursor_after: str | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("next_attempt_at", "claimed_at", "created_at")
    @classmethod
    def normalize_item_time(cls, value: datetime | None) -> datetime | None:
        """Normalize work-item timestamps to UTC."""
        return ensure_utc(value) if value is not None else None


class EndpointSyncResult(BaseModel):
    """Result of executing one endpoint work item."""

    work_item_id: str
    status: DataSyncStatus
    raw_snapshot_ids: tuple[str, ...] = Field(default_factory=tuple)
    fact_count: int = 0
    canonical_count: int = 0
    quality_issue_count: int = 0
    cursor_before: str | None = None
    cursor_after: str | None = None
    retry_after_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    finished_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("finished_at")
    @classmethod
    def normalize_finished_at(cls, value: datetime) -> datetime:
        """Normalize completion timestamp to UTC."""
        return ensure_utc(value)
