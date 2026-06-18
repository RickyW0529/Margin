"""Data models for the portfolio package.

Defines the core domain objects used to represent trades, positions,
portfolios, investment theses, alert events, and import audit records.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.data.standardize import normalize_symbol


def _utc_now() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        The current date and time in UTC.
    """
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware in UTC.

    Args:
        value: A datetime instance, which may be naive or aware.

    Returns:
        The input datetime normalized to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TradeSide(StrEnum):
    """Direction of a trade.

    Attributes:
        BUY: Purchase of an asset.
        SELL: Sale of an asset.
        DIVIDEND: Dividend distribution.
        SPLIT: Stock split event.
    """

    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    SPLIT = "split"


class TradeSource(StrEnum):
    """Origin of a trade record, used for audit trails.

    Attributes:
        MANUAL: Manually entered trade.
        CSV: Imported from a CSV file.
        EXCEL: Imported from an Excel file.
        BROKER_PLUGIN: Imported via a broker plugin.
    """

    MANUAL = "manual"
    CSV = "csv"
    EXCEL = "excel"
    BROKER_PLUGIN = "broker_plugin"


class PositionHealthStatus(StrEnum):
    """Health classification of a position.

    Attributes:
        HEALTHY: Position is within expected parameters.
        WATCH: Position requires monitoring.
        RISK: Position has triggered a risk condition.
        INVALIDATED: Investment thesis has been invalidated.
        DATA_MISSING: Required market or reference data is unavailable.
        EVENT_PENDING: A corporate action or review event is pending.
    """

    HEALTHY = "healthy"
    WATCH = "watch"
    RISK = "risk"
    INVALIDATED = "invalidated"
    DATA_MISSING = "data_missing"
    EVENT_PENDING = "event_pending"


class ThesisStatus(StrEnum):
    """Lifecycle status of an investment thesis.

    Attributes:
        THESIS_VALID: Thesis remains valid.
        REVIEW_REQUIRED: Thesis needs review.
        RISK_ALERT: Thesis has generated a risk alert.
        THESIS_INVALIDATED: Thesis is no longer valid.
    """

    THESIS_VALID = "thesis_valid"
    REVIEW_REQUIRED = "review_required"
    RISK_ALERT = "risk_alert"
    THESIS_INVALIDATED = "thesis_invalidated"


# ---------------------------------------------------------------------------
# Trade records
# ---------------------------------------------------------------------------


class Trade(BaseModel):
    """A single immutable trade record.

    Trades are frozen after creation and persisted unchanged. When amount is
    zero at initialization, it is automatically derived from quantity, price,
    fee, and tax.

    Attributes:
        trade_id: Unique identifier for the trade.
        portfolio_id: Identifier of the portfolio that owns the trade.
        symbol: Normalized symbol of the traded instrument.
        side: Direction of the trade.
        quantity: Number of units traded.
        price: Execution price per unit.
        amount: Total monetary amount including fees and tax.
        fee: Transaction fee paid.
        tax: Tax paid on the trade.
        traded_at: Timestamp when the trade occurred.
        source: Origin of the trade record.
        source_ref: Optional external reference from the source system.
        raw_hash: Optional hash of the raw import row for deduplication.
        imported_at: Timestamp when the record was created or imported.
        note: Optional free-text note.
    """

    trade_id: str
    portfolio_id: str
    symbol: str
    side: TradeSide
    quantity: float
    price: float
    amount: float = 0.0
    fee: float = 0.0
    tax: float = 0.0
    traded_at: datetime
    source: TradeSource = TradeSource.MANUAL
    source_ref: str | None = None
    raw_hash: str | None = None
    imported_at: datetime = Field(default_factory=_utc_now)
    note: str | None = None

    model_config = {"frozen": True}

    @field_validator("traded_at", "imported_at")
    @classmethod
    def normalize_trade_timestamp(cls, value: datetime) -> datetime:
        """Normalize trade timestamps to UTC."""
        return _ensure_utc(value)

    def model_post_init(self, __context: Any) -> None:
        """Compute the trade amount if it was not provided.

        Args:
            __context: Pydantic initialization context.
        """
        if self.amount == 0.0:
            total = self.quantity * self.price + self.fee + self.tax
            object.__setattr__(self, "amount", total)


# ---------------------------------------------------------------------------
# Investment thesis
# ---------------------------------------------------------------------------


class PositionThesis(BaseModel):
    """Investment thesis attached to a position.

    Captures the rationale, entry/hold/invalidation conditions, target holding
    horizon, and the next scheduled review. Changes create new versions while
    older versions are retained for audit.

    Attributes:
        thesis_id: Unique identifier for the thesis.
        position_id: Identifier of the associated position.
        thesis: Textual description of the investment rationale.
        entry_conditions: Conditions that justify opening the position.
        hold_conditions: Conditions that justify keeping the position.
        invalidation_conditions: Conditions that would invalidate the thesis.
        target_horizon: Target review windows in days.
        next_review_at: Optional scheduled timestamp for the next review.
        status: Current lifecycle status of the thesis.
        version: Version number starting at one.
        created_at: Timestamp when this thesis version was created.
    """

    thesis_id: str
    position_id: str
    thesis: str
    entry_conditions: list[str] = Field(default_factory=list)
    hold_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    target_horizon: list[int] = Field(default_factory=lambda: [60, 120])
    next_review_at: datetime | None = None
    status: ThesisStatus = ThesisStatus.THESIS_VALID
    version: int = 1
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = {"frozen": True}

    @field_validator("next_review_at", "created_at")
    @classmethod
    def normalize_thesis_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize thesis timestamps to UTC."""
        return _ensure_utc(value) if value is not None else None


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class Position(BaseModel):
    """A single investment position derived from trade records.

    Corresponds to the PORTFOLIO 1→N POSITION relationship. Cost basis and
    profit/loss figures are computed by CostCalculator and stored here.

    Attributes:
        position_id: Unique identifier for the position.
        portfolio_id: Identifier of the portfolio that owns the position.
        symbol: Normalized symbol of the instrument held.
        quantity: Number of units currently held.
        cost_price: Average cost price per unit.
        cost_amount: Total cost amount for the position.
        current_price: Latest available market price, if known.
        market_value: Current market value, if known.
        unrealized_pnl: Unrealized profit or loss, if known.
        unrealized_pnl_pct: Unrealized profit or loss percentage, if known.
        industry: Optional industry classification.
        health_status: Current health classification.
        thesis: Optional investment thesis associated with the position.
        updated_at: Timestamp when the position was last updated.
    """

    position_id: str
    portfolio_id: str
    symbol: str
    quantity: float = 0.0
    cost_price: float = 0.0
    cost_amount: float = 0.0
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    industry: str | None = None
    health_status: PositionHealthStatus = PositionHealthStatus.HEALTHY
    thesis: PositionThesis | None = None
    updated_at: datetime = Field(default_factory=_utc_now)

    model_config = {"frozen": True}

    @field_validator("updated_at")
    @classmethod
    def normalize_position_timestamp(cls, value: datetime) -> datetime:
        """Normalize position timestamps to UTC."""
        return _ensure_utc(value)


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------


class Portfolio(BaseModel):
    """An investment portfolio owned by a user.

    Corresponds to the USER 1→N PORTFOLIO relationship.

    Attributes:
        portfolio_id: Unique identifier for the portfolio.
        user_id: Identifier of the owning user.
        name: Human-readable portfolio name.
        cash: Cash balance available in the portfolio.
        created_at: Timestamp when the portfolio was created.
    """

    portfolio_id: str
    user_id: str
    name: str
    cash: float = 0.0
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_portfolio_timestamp(cls, value: datetime) -> datetime:
        """Normalize portfolio timestamps to UTC."""
        return _ensure_utc(value)


# ---------------------------------------------------------------------------
# Alert events
# ---------------------------------------------------------------------------


class AlertEvent(BaseModel):
    """Alert triggered for a position or thesis.

    The alerting engine is implemented in the holdings monitoring module;
    this model only defines the data structure.

    Attributes:
        alert_id: Unique identifier for the alert.
        position_id: Identifier of the associated position.
        alert_type: Classification of the alert.
        severity: Alert severity level.
        message: Human-readable alert message.
        triggered_at: Timestamp when the alert was triggered.
        evidence_refs: References to supporting evidence or documents.
    """

    alert_id: str
    position_id: str
    alert_type: str
    severity: str = "P2"
    message: str
    triggered_at: datetime = Field(default_factory=_utc_now)
    evidence_refs: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}

    @field_validator("triggered_at")
    @classmethod
    def normalize_alert_timestamp(cls, value: datetime) -> datetime:
        """Normalize alert timestamps to UTC."""
        return _ensure_utc(value)


# ---------------------------------------------------------------------------
# Import audit
# ---------------------------------------------------------------------------


class ImportRecord(BaseModel):
    """Audit record for a batch of imported trades.

    One record is created for each import session regardless of source
    (manual, CSV, Excel, or broker plugin). The record is immutable.

    Attributes:
        import_id: Unique identifier for the import session.
        portfolio_id: Identifier of the target portfolio.
        source: Origin of the imported trades.
        file_name: Optional name of the imported file.
        trade_count: Number of trades accepted in the import.
        rejected_count: Number of trades rejected during validation.
        imported_at: Timestamp when the import occurred.
        raw_hash: Optional hash of the raw import data.
        errors: List of validation or import errors encountered.
    """

    import_id: str
    portfolio_id: str
    source: TradeSource
    file_name: str | None = None
    trade_count: int = 0
    rejected_count: int = 0
    imported_at: datetime = Field(default_factory=_utc_now)
    raw_hash: str | None = None
    errors: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}

    @field_validator("imported_at")
    @classmethod
    def normalize_import_timestamp(cls, value: datetime) -> datetime:
        """Normalize import timestamps to UTC."""
        return _ensure_utc(value)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def make_trade(
    portfolio_id: str,
    symbol: str,
    side: TradeSide,
    quantity: float,
    price: float,
    traded_at: datetime,
    **kwargs: Any,
) -> Trade:
    """Create a new Trade instance with a generated id and normalized symbol.

    Args:
        portfolio_id: Identifier of the portfolio that owns the trade.
        symbol: Raw symbol to be normalized before storage.
        side: Direction of the trade.
        quantity: Number of units traded.
        price: Execution price per unit.
        traded_at: Timestamp when the trade occurred.
        **kwargs: Additional fields forwarded to the Trade constructor.

    Returns:
        A fully initialized Trade instance.
    """
    import uuid

    return Trade(
        trade_id=f"trd_{uuid.uuid4().hex[:12]}",
        portfolio_id=portfolio_id,
        symbol=normalize_symbol(symbol),
        side=side,
        quantity=quantity,
        price=price,
        traded_at=traded_at,
        **kwargs,
    )
