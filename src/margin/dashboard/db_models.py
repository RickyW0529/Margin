"""SQLAlchemy rows owned by the research candidate dashboard module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from margin.storage.base import Base


class DashboardRunRow(Base):
    """Run-level dashboard aggregate.."""

    __tablename__ = "dashboard_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    universe: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstained_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aborted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list[DashboardItemRow]] = relationship(
        "DashboardItemRow",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class DashboardItemRow(Base):
    """Symbol-level item inside a dashboard run.."""

    __tablename__ = "dashboard_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("dashboard_runs.run_id"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    statement: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    workflow_run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    abstain_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_adjustment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    counter_arguments: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[DashboardRunRow] = relationship(
        "DashboardRunRow",
        back_populates="items",
    )


class DashboardFeedbackRow(Base):
    """Append-only feedback record.."""

    __tablename__ = "dashboard_feedback"

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
