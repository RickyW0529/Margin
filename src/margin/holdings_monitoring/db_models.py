"""SQLAlchemy ORM models for module 09 holdings monitoring."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AlertEventRow(Base):
    """Append-only persisted alert event.

    Attributes:
        alert_id: Primary key identifier of the alert.
        portfolio_id: Foreign key to the portfolio that owns the position.
        position_id: Identifier of the monitored position.
        symbol: Traded symbol or ticker.
        alert_type: Categorized alert type.
        severity: Alert priority / severity string.
        message: Human-readable alert message.
        rule_name: Name of the monitoring rule that triggered the alert.
        triggered_at: UTC timestamp when the alert was triggered.
        evidence_refs: List of evidence references associated with the alert.
        changed_thesis: Whether the alert indicates a thesis change.
        acknowledged_at: UTC timestamp when the alert was acknowledged, if any.
    """

    __tablename__ = "alert_events"
    __table_args__ = (
        Index("ix_alert_events_portfolio_position", "portfolio_id", "position_id"),
        Index("ix_alert_events_severity_time", "severity", "triggered_at"),
    )

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[str] = mapped_column(String(96), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(80), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    changed_thesis: Mapped[bool] = mapped_column(Boolean, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionReviewRow(Base):
    """Append-only persisted manual review record.

    Attributes:
        review_id: Primary key identifier of the review.
        portfolio_id: Foreign key to the portfolio that owns the position.
        position_id: Identifier of the reviewed position.
        alert_id: Optional foreign key to the alert that prompted the review.
        decision: Recorded review decision string.
        rationale: Human-readable explanation of the review decision.
        action_taken_at: UTC timestamp when action was taken, if any.
        created_at: UTC timestamp when the review record was created.
    """

    __tablename__ = "position_reviews"
    __table_args__ = (
        Index("ix_position_reviews_portfolio_position", "portfolio_id", "position_id"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[str] = mapped_column(String(96), nullable=False)
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_events.alert_id", ondelete="RESTRICT")
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
