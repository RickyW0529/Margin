"""SQLAlchemy rows owned by the multi-agent research module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ResearchSnapshotRow(Base):
    """Append-only serialized research snapshot."""

    __tablename__ = "research_snapshots"
    __table_args__ = (
        Index("ix_research_snapshots_run_created", "run_id", "created_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workflow_state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIGraphRunRow(Base):
    """One durable execution of the v0.2 AI delta review graph."""

    __tablename__ = "ai_graph_runs"
    __table_args__ = (
        Index("ix_ai_graph_runs_security_decision", "security_id", "decision_at"),
        Index("ix_ai_graph_runs_context", "context_snapshot_id"),
    )

    graph_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    context_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    context_input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_mode: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(32))
    effective_assessment_id: Mapped[str | None] = mapped_column(String(64))
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIGraphNodeRunRow(Base):
    """Append-only node attempt with input/output hashes and error metadata."""

    __tablename__ = "ai_graph_node_runs"
    __table_args__ = (
        UniqueConstraint(
            "graph_run_id",
            "node_name",
            "attempt_no",
            name="uq_ai_graph_node_attempt",
        ),
        Index("ix_ai_graph_node_runs_graph_node", "graph_run_id", "node_name"),
    )

    node_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(96))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(128))
    tool_policy_version: Mapped[str | None] = mapped_column(String(64))
    error_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIGraphCheckpointRow(Base):
    """Immutable graph checkpoint for crash recovery and identity validation."""

    __tablename__ = "ai_graph_checkpoints"
    __table_args__ = (
        Index("ix_ai_graph_checkpoints_created", "graph_run_id", "created_at"),
    )

    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    checkpoint_ns: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(96))
    identity_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    state_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checkpoint_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolCallRecordRow(Base):
    """Audited allowed or denied scoped tool call."""

    __tablename__ = "tool_call_records"
    __table_args__ = (
        Index("ix_tool_call_records_graph_node", "graph_run_id", "node_name"),
    )

    tool_call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(96))
    request_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LLMCallRecordRow(Base):
    """Audited structured LLM call with a unique billing key."""

    __tablename__ = "llm_call_records"
    __table_args__ = (
        UniqueConstraint("billing_key", name="uq_llm_call_billing_key"),
        Index("ix_llm_call_records_graph_node", "graph_run_id", "node_name"),
    )

    llm_call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    billing_key: Mapped[str] = mapped_column(String(128), nullable=False)
    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(96))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    request_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchDeltaReviewRow(Base):
    """Immutable terminal delta-review result."""

    __tablename__ = "research_delta_reviews"
    __table_args__ = (
        UniqueConstraint("graph_run_id", name="uq_research_delta_review_graph_run"),
        Index("ix_research_delta_reviews_security_decision", "security_id", "decision_at"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    context_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_effective_assessment_id: Mapped[str | None] = mapped_column(String(64))
    effective_assessment_id: Mapped[str | None] = mapped_column(String(64))
    assessment_freshness: Mapped[str | None] = mapped_column(String(32))
    stale_reason: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valuation_view: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="uncertain",
    )
    changed_assumptions: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tool_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchDeltaOutboxRow(Base):
    """Transactional publication event for a terminal delta review."""

    __tablename__ = "research_delta_outbox"
    __table_args__ = (
        UniqueConstraint(
            "graph_run_id",
            "event_type",
            name="uq_research_delta_outbox_event",
        ),
        Index("ix_research_delta_outbox_status_next", "status", "next_attempt_at"),
    )

    outbox_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_graph_runs.graph_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
