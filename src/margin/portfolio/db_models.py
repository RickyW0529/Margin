"""SQLAlchemy ORM models for persisting portfolios, trades, and investment theses.

The models in this module map the portfolio domain objects to PostgreSQL tables
using SQLAlchemy 2.0 style type-annotated ``Mapped`` columns. Each model is
append-only or versioned where appropriate to support audit and history.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class PortfolioRow(Base):
    """Persisted portfolio state.

    Attributes:
        portfolio_id: Unique identifier for the portfolio (primary key).
        user_id: Identifier of the portfolio owner.
        name: Human-readable portfolio name.
        cash: Cash balance stored as a high-precision decimal.
        created_at: Timestamp when the portfolio was created.
    """

    __tablename__ = "portfolios"

    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TradeRow(Base):
    """Append-only persisted trade record.

    Attributes:
        trade_id: Unique identifier for the trade (primary key).
        portfolio_id: Identifier of the portfolio that owns the trade.
        symbol: Normalized trading symbol.
        side: Trade side string (e.g. ``buy`` or ``sell``).
        quantity: Number of units traded.
        price: Execution price per unit.
        amount: Total monetary amount including fees and tax.
        fee: Transaction fee paid.
        tax: Tax paid on the trade.
        traded_at: Timestamp when the trade occurred.
        source: Origin of the trade record.
        source_ref: Optional external reference from the source system.
        raw_hash: Optional hash of the raw import row for deduplication.
        imported_at: Timestamp when the record was imported or created.
        note: Optional free-text note.
    """

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_portfolio_symbol_time", "portfolio_id", "symbol", "traded_at"),
    )

    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(256))
    raw_hash: Mapped[str | None] = mapped_column(String(96))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class PositionThesisRow(Base):
    """Append-only persisted investment thesis version.

    Attributes:
        thesis_id: Unique identifier for the thesis version (primary key).
        portfolio_id: Identifier of the portfolio that owns the thesis.
        position_id: Identifier of the associated position.
        thesis: Textual description of the investment rationale.
        entry_conditions: Conditions that justify opening the position.
        hold_conditions: Conditions that justify keeping the position.
        invalidation_conditions: Conditions that would invalidate the thesis.
        target_horizon: Target review windows in days.
        next_review_at: Optional scheduled timestamp for the next review.
        status: Current lifecycle status of the thesis.
        version: Monotonically increasing version number.
        created_at: Timestamp when this thesis version was created.
    """

    __tablename__ = "position_theses"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "position_id",
            "version",
            name="uq_position_thesis_version",
        ),
        Index(
            "ix_position_theses_portfolio_position",
            "portfolio_id",
            "position_id",
            "version",
        ),
    )

    thesis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    position_id: Mapped[str] = mapped_column(String(96), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    entry_conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    hold_conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    invalidation_conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    target_horizon: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
