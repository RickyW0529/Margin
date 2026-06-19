"""Shared core domain models.

Lightweight Pydantic models that cross layer boundaries, e.g. audit records
emitted by services and persisted by repositories.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class AuditLogRecord(BaseModel):
    """Immutable audit record for critical business objects."""

    record_id: str = Field(default_factory=lambda: f"ar_{uuid.uuid4().hex[:12]}")
    record_type: str
    object_id: str | None = None
    trace_id: str = ""
    input_hash: str | None = None
    output_hash: str | None = None
    payload_json: dict[str, Any] | None = None
    recorded_at: datetime = Field(default_factory=utc_now)
    service_version: str = "0.1.0"

    model_config = {"frozen": True}
    # Frozen prevents accidental mutation after the record is emitted,
    # preserving the audit trail's integrity.

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        """Coerce the timestamp to UTC to keep audit ordering deterministic."""
        return ensure_utc(value)
