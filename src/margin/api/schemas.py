"""FastAPI request and response schemas for the Margin API.

This module defines Pydantic models used to validate incoming request bodies
and serialise outgoing responses. Schemas wrap domain models from the
portfolio layer so the API can remain decoupled from internal storage types.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from margin.portfolio.models import (
    ImportRecord,
    Portfolio,
    ThesisStatus,
    Trade,
    TradeSide,
)
from margin.portfolio.service import PortfolioOverview


class TradeCreate(BaseModel):
    """Request body for manually entering a single trade.

    Attributes:
        symbol: Ticker or instrument identifier. Must be a non-empty string.
        side: Whether the trade is a buy or sell.
        quantity: Number of shares or units traded. Must be greater than zero.
        price: Execution price per unit. Must be greater than zero.
        traded_at: Timestamp when the trade occurred.
        fee: Optional brokerage fee. Defaults to ``0`` and must be non-negative.
        tax: Optional tax amount. Defaults to ``0`` and must be non-negative.
        note: Optional free-form note attached to the trade.
    """

    symbol: str = Field(min_length=1)
    side: TradeSide
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    traded_at: datetime
    fee: float = Field(default=0, ge=0)
    tax: float = Field(default=0, ge=0)
    note: str | None = None


class CSVImportRequest(BaseModel):
    """Request body for importing trades from CSV content.

    Attributes:
        content: Raw CSV text. Must be a non-empty string.
        field_mapping: Optional mapping from CSV column names to canonical
            trade field names, allowing flexible source formats.
    """

    content: str = Field(min_length=1)
    field_mapping: dict[str, str] | None = None


class CSVImportResponse(BaseModel):
    """Response payload returned after a CSV import completes.

    Attributes:
        trades: The trades created from the imported rows.
        record: The import record that tracks the outcome and lineage of the
            import operation.
    """

    trades: list[Trade]
    record: ImportRecord


class ThesisUpdate(BaseModel):
    """Request body for creating a new investment thesis version.

    Attributes:
        portfolio_id: Identifier of the portfolio that owns the position.
        thesis: The main investment thesis text. Must be non-empty.
        entry_conditions: Conditions that justify entering the position.
        hold_conditions: Conditions that justify keeping the position open.
        invalidation_conditions: Conditions that would invalidate the thesis.
        target_horizon: Target review horizons in days. Defaults to ``[60, 120]``.
        next_review_at: Optional timestamp for the next scheduled review.
        status: Current thesis status. Defaults to ``ThesisStatus.THESIS_VALID``.
    """

    portfolio_id: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    entry_conditions: list[str] = Field(default_factory=list)
    hold_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    target_horizon: list[int] = Field(default_factory=lambda: [60, 120])
    next_review_at: datetime | None = None
    status: ThesisStatus = ThesisStatus.THESIS_VALID


class PortfolioDashboardResponse(BaseModel):
    """Response payload that combines identity and overview for a portfolio.

    Attributes:
        portfolio: The portfolio identity and metadata.
        overview: Aggregated dashboard metrics for the portfolio.
    """

    portfolio: Portfolio
    overview: PortfolioOverview
