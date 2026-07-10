"""SQLAlchemy rows for the v0.4 agent runtime context store."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AgentRuntimeRunRow(Base):
    """One durable agent runtime run.."""

    __tablename__ = "agent_runtime_runs"
    __table_args__ = (Index("ix_agent_runtime_runs_type_started", "run_type", "started_at"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    permission_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRuntimeStepRow(Base):
    """One planned or executed expert step.."""

    __tablename__ = "agent_runtime_steps"
    __table_args__ = (Index("ix_agent_runtime_steps_run_created", "run_id", "created_at"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expert_agent_name: Mapped[str] = mapped_column(String(96), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRuntimeArtifactRow(Base):
    """Immutable artifact stored in the Shared Context Store.."""

    __tablename__ = "agent_runtime_artifacts"
    __table_args__ = (
        Index("ix_agent_runtime_artifacts_run_type", "run_id", "artifact_type"),
        Index("ix_agent_runtime_artifacts_created", "run_id", "created_at"),
    )

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(96), nullable=False)
    producer_agent: Mapped[str] = mapped_column(String(96), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRuntimeGuardrailDecisionRow(Base):
    """Audited guardrail decision.."""

    __tablename__ = "agent_runtime_guardrail_decisions"
    __table_args__ = (
        Index("ix_agent_runtime_guardrails_run_stage", "run_id", "stage"),
        Index("ix_agent_runtime_guardrails_created", "run_id", "created_at"),
    )

    decision_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed: Mapped[bool] = mapped_column(nullable=False)
    evaluation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRuntimeScheduleRow(Base):
    """One persisted user-facing agent schedule.."""

    __tablename__ = "agent_runtime_schedules"
    __table_args__ = (Index("ix_agent_runtime_schedules_enabled_next", "enabled", "next_run_at"),)

    schedule_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    hour: Mapped[int] = mapped_column(nullable=False)
    minute: Mapped[int] = mapped_column(nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe: Mapped[str] = mapped_column(String(32), nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationWorkerArtifactRow(Base):
    """Immutable durable output of one recommendation pipeline worker."""

    __tablename__ = "recommendation_worker_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "orchestration_run_id",
            "worker_name",
            name="uq_recommendation_worker_artifacts_run_worker",
        ),
        Index(
            "ix_recommendation_worker_artifacts_scope_decision",
            "scope_version_id",
            "decision_at",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    orchestration_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_name: Mapped[str] = mapped_column(String(96), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentChatSessionRow(Base):
    """One persisted user-facing chat session.."""

    __tablename__ = "agent_chat_sessions"
    __table_args__ = (Index("ix_agent_chat_sessions_updated", "updated_at"),)

    session_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scope_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentChatMessageRow(Base):
    """One persisted user or assistant chat message.."""

    __tablename__ = "agent_chat_messages"
    __table_args__ = (
        Index("ix_agent_chat_messages_session_created", "session_id", "created_at"),
        Index("ix_agent_chat_messages_run", "run_id"),
    )

    message_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(96), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
