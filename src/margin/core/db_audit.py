"""SQLAlchemy ORM model for immutable audit records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AuditLogRecordRow(Base):
    """Append-only audit record persisted in PostgreSQL."""

    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_record_type", "record_type"),
        Index("ix_audit_records_object_id", "object_id"),
        Index("ix_audit_records_trace_id", "trace_id"),
        Index("ix_audit_records_recorded_at", "recorded_at"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_hash: Mapped[str | None] = mapped_column(String(96), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(96), nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
