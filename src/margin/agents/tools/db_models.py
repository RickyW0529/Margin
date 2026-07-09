"""SQLAlchemy rows for ToolGateway catalog and audit tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ToolCatalogVersionRow(Base):
    """One immutable ToolCatalog version snapshot."""

    __tablename__ = "tool_catalog_versions"
    __table_args__ = (
        Index("ix_tool_catalog_versions_active", "is_active"),
        {"schema": "tool"},
    )

    tool_catalog_version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    catalog_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    catalog_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)


class ToolCallRow(Base):
    """One audited ToolGateway call."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_run_task", "run_id", "task_id"),
        Index("ix_tool_calls_tool_started", "tool_name", "started_at"),
        {"schema": "tool"},
    )

    tool_call_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    caller_agent: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    input_redacted_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capability_token_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(nullable=False, default=False)


class ToolResultRow(Base):
    """One audited redacted ToolGateway result."""

    __tablename__ = "tool_results"
    __table_args__ = ({"schema": "tool"},)

    tool_call_id: Mapped[str] = mapped_column(Text, primary_key=True)
    output_hash: Mapped[str | None] = mapped_column(Text)
    output_redacted_json: Mapped[dict | None] = mapped_column(JSONB)
    output_artifact_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    output_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolRateLimitBucketRow(Base):
    """One tool rate-limit bucket."""

    __tablename__ = "tool_rate_limit_buckets"
    __table_args__ = (
        Index("ix_tool_rate_limit_tool_window", "tool_name", "window_start"),
        {"schema": "tool"},
    )

    bucket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[int] = mapped_column(nullable=False)
    limit_count: Mapped[int] = mapped_column(nullable=False)
    used_count: Mapped[int] = mapped_column(nullable=False, default=0)

