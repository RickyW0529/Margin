"""SQLAlchemy rows for v1 Agent PromptBundle persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class PromptTemplateRow(Base):
    """One versioned prompt template."""

    __tablename__ = "prompt_templates"
    __table_args__ = (
        Index("ix_prompt_templates_prompt", "prompt_id"),
        {"schema": "prompt"},
    )

    prompt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    output_schema_ref: Mapped[str | None] = mapped_column(Text)
    safety_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptBundleRow(Base):
    """One versioned PromptBundle metadata row."""

    __tablename__ = "prompt_bundles"
    __table_args__ = (
        Index("ix_prompt_bundles_target_active", "target_agent_type", "is_active"),
        {"schema": "prompt"},
    )

    prompt_bundle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    target_agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    template_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    model_profile_ref: Mapped[str] = mapped_column(Text, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptRenderHistoryRow(Base):
    """One prompt render audit row without raw rendered prompt text."""

    __tablename__ = "prompt_render_history"
    __table_args__ = (
        Index("ix_prompt_render_history_run", "run_id"),
        Index("ix_prompt_render_history_bundle", "prompt_bundle_id"),
        {"schema": "prompt"},
    )

    render_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_bundle_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    variables_hash: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LLMCallAuditRow(Base):
    """One LLM provider call audit row linked to prompt render history."""

    __tablename__ = "llm_call_audits"
    __table_args__ = (
        Index("ix_llm_call_audits_run", "run_id"),
        Index("ix_llm_call_audits_prompt_render", "prompt_render_id"),
        {"schema": "prompt"},
    )

    llm_call_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_render_id: Mapped[str] = mapped_column(Text, nullable=False)
    input_token_count: Mapped[int | None] = mapped_column()
    output_token_count: Mapped[int | None] = mapped_column()
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
