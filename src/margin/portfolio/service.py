"""PortfolioService — portfolio service integrating trades, cost, risk, and dashboards.

Corresponds to spec 02 §3 interface contract (architecture §17.3 portfolio API).
Corresponds to architecture §17 portfolio service architecture:
Portfolio Service → cost/quantity calculation / portfolio risk engine / investment thesis tracking.
Corresponds to plan 0203: portfolio overview view / single-position detail view / API integration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from margin.portfolio.cost import CostCalculator
from margin.portfolio.importer import TradeImporter
from margin.portfolio.models import (
    ImportRecord,
    Portfolio,
    Position,
    PositionHealthStatus,
    PositionThesis,
    ThesisStatus,
    Trade,
    TradeSide,
)
from margin.portfolio.risk import PortfolioRiskEngine, PortfolioRiskReport

# ---------------------------------------------------------------------------
# Dashboard view models (product §8.1 / §8.2)
# ---------------------------------------------------------------------------


class PortfolioOverview(BaseModel):
    """Portfolio overview dashboard (product §8.1).

    Attributes:
        portfolio_id: Identifier of the portfolio.
        portfolio_name: Human-readable portfolio name.
        total_assets: Cash plus total market value.
        cash: Available cash balance.
        market_value: Total market value of all positions.
        today_pnl: Profit/loss for the current trading day, if available.
        cumulative_pnl: Cumulative unrealized profit/loss across positions.
        portfolio_volatility: Optional volatility metric from the risk engine.
        max_drawdown: Optional drawdown metric from the risk engine.
        industry_exposure: Mapping from industry to portfolio weight.
        style_exposure: Mapping from style label (growth/value) to weight.
        high_risk_count: Number of positions flagged as high risk or invalidated.
        upcoming_events: List of upcoming corporate events for tracked symbols.
        position_count: Number of positions in the portfolio.
        updated_at: Timestamp when the overview was generated.
    """

    portfolio_id: str
    portfolio_name: str
    total_assets: float = 0.0
    cash: float = 0.0
    market_value: float = 0.0
    today_pnl: float | None = None
    cumulative_pnl: float = 0.0
    portfolio_volatility: float | None = None
    max_drawdown: float | None = None
    industry_exposure: dict[str, float] = Field(default_factory=dict)
    style_exposure: dict[str, float] = Field(default_factory=dict)
    high_risk_count: int = 0
    upcoming_events: list[dict[str, Any]] = Field(default_factory=list)
    position_count: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


class PositionDetail(BaseModel):
    """Single position detail view (product §8.2).

    Attributes:
        position_id: Identifier of the position.
        symbol: Traded symbol or ticker.
        quantity: Number of shares or units held.
        cost_price: Average cost per share.
        cost_amount: Total cost amount.
        current_price: Latest market price, if available.
        market_value: Current market value, if available.
        unrealized_pnl: Unrealized profit/loss, if available.
        unrealized_pnl_pct: Unrealized profit/loss percentage, if available.
        industry: Industry classification, if available.
        health_status: Data quality/risk health status of the position.
        thesis: Latest investment thesis for the position, if any.
        trade_history: List of historical trades for the symbol.
        weight: Portfolio weight of the position.
        updated_at: Timestamp when the detail was generated.
    """

    position_id: str
    symbol: str
    quantity: float
    cost_price: float
    cost_amount: float
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    industry: str | None = None
    health_status: PositionHealthStatus = PositionHealthStatus.HEALTHY
    thesis: PositionThesis | None = None
    trade_history: list[dict[str, Any]] = Field(default_factory=list)
    weight: float | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


# ---------------------------------------------------------------------------
# PortfolioService
# ---------------------------------------------------------------------------


class PortfolioService:
    """Portfolio service — externally exposed portfolio management capabilities.

    Integrates trade import, cost calculation, risk engine, and dashboard views.
    Corresponds to architecture §17: Portfolio Service → cost calculation /
    risk engine / investment thesis tracking.

    Example:
        service = PortfolioService()
        portfolio = service.create_portfolio("user_001", "My Portfolio")
        service.add_trade(
            portfolio.portfolio_id, "000001.SZ", "buy", 1000, 10.5, traded_at=datetime.now()
        )
        positions = service.get_positions(portfolio.portfolio_id)
        overview = service.get_overview(portfolio.portfolio_id)

    Attributes:
        _portfolios: In-memory mapping from portfolio_id to Portfolio.
        _trades: In-memory mapping from portfolio_id to list of Trade records.
        _positions_cache: Cached positions per portfolio (invalidated on trade changes).
        _theses: In-memory mapping from portfolio_id to list of PositionThesis records.
        _importer: Trade importer used for manual and CSV imports.
        _cost_calculator: Calculator used to derive positions from trades.
        _risk_engine: Engine used to compute portfolio risk metrics.
    """

    def __init__(
        self,
        cost_calculator: CostCalculator | None = None,
        risk_engine: PortfolioRiskEngine | None = None,
    ) -> None:
        """Initialize the portfolio service.

        Args:
            cost_calculator: Optional CostCalculator instance. A default is created if omitted.
            risk_engine: Optional PortfolioRiskEngine instance. A default is created if omitted.
        """
        self._portfolios: dict[str, Portfolio] = {}
        self._trades: dict[str, list[Trade]] = {}
        self._positions_cache: dict[str, list[Position]] = {}
        self._theses: dict[str, list[PositionThesis]] = {}
        self._importer = TradeImporter()
        self._cost_calculator = cost_calculator or CostCalculator()
        self._risk_engine = risk_engine or PortfolioRiskEngine()

    def create_portfolio(
        self,
        user_id: str,
        name: str,
        cash: float = 0.0,
    ) -> Portfolio:
        """Create a new portfolio for a user.

        Args:
            user_id: Identifier of the portfolio owner.
            name: Human-readable portfolio name.
            cash: Initial cash balance.

        Returns:
            The newly created Portfolio instance.
        """
        import uuid

        portfolio = Portfolio(
            portfolio_id=f"pf_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            name=name,
            cash=cash,
        )
        self._portfolios[portfolio.portfolio_id] = portfolio
        self._trades[portfolio.portfolio_id] = []
        self._theses[portfolio.portfolio_id] = []
        return portfolio

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        """Retrieve a portfolio by identifier.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            The matching Portfolio instance.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        if portfolio_id not in self._portfolios:
            raise KeyError(f"Portfolio '{portfolio_id}' not found")
        return self._portfolios[portfolio_id]

    def add_trade(
        self,
        portfolio_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        traded_at: datetime,
        fee: float = 0.0,
        tax: float = 0.0,
        note: str | None = None,
    ) -> Trade:
        """Manually add a trade to a portfolio (corresponds to POST /portfolios/{id}/trades).

        Args:
            portfolio_id: Identifier of the portfolio.
            symbol: Traded symbol or ticker.
            side: Trade side, e.g. "buy" or "sell".
            quantity: Number of shares or units.
            price: Execution price.
            traded_at: Trade execution timestamp.
            fee: Transaction fee.
            tax: Transaction tax.
            note: Optional note or memo.

        Returns:
            The created Trade record.
        """
        self._ensure_portfolio(portfolio_id)
        trade = self._importer.add_trade_manual(
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            traded_at=traded_at,
            fee=fee,
            tax=tax,
            note=note,
        )
        self._append_trades(portfolio_id, [trade])
        return trade

    def import_csv(
        self,
        portfolio_id: str,
        content: str,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from CSV content (corresponds to POST /portfolios/{id}/imports).

        Args:
            portfolio_id: Identifier of the portfolio.
            content: Raw CSV string.
            field_mapping: Optional mapping from CSV columns to expected trade fields.

        Returns:
            A tuple of imported trades and the import record.
        """
        self._ensure_portfolio(portfolio_id)
        trades, record = self._importer.import_csv_bytes(
            portfolio_id=portfolio_id,
            content=content,
            field_mapping=field_mapping,
        )
        self._append_trades(portfolio_id, trades)
        return trades, record

    def import_csv_file(
        self,
        portfolio_id: str,
        file_path: str,
        field_mapping: dict[str, str] | None = None,
    ) -> tuple[list[Trade], ImportRecord]:
        """Import trades from a CSV file path.

        Args:
            portfolio_id: Identifier of the portfolio.
            file_path: Path to the CSV file.
            field_mapping: Optional mapping from CSV columns to expected trade fields.

        Returns:
            A tuple of imported trades and the import record.
        """
        from pathlib import Path

        self._ensure_portfolio(portfolio_id)
        trades, record = self._importer.import_csv(
            portfolio_id=portfolio_id,
            file_path=Path(file_path),
            field_mapping=field_mapping,
        )
        self._append_trades(portfolio_id, trades)
        return trades, record

    def get_trades(self, portfolio_id: str) -> list[Trade]:
        """Return all trade records for a portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            A copy of the portfolio's trade list.
        """
        self._ensure_portfolio(portfolio_id)
        return list(self._trades[portfolio_id])

    def get_positions(
        self,
        portfolio_id: str,
        current_prices: dict[str, float] | None = None,
    ) -> list[Position]:
        """Return the current positions for a portfolio.

        Args:
            portfolio_id: Identifier of the portfolio.
            current_prices: Optional mapping from symbol to current market price.

        Returns:
            List of Position instances with attached theses.
        """
        self._ensure_portfolio(portfolio_id)
        trades = self._trades[portfolio_id]
        positions = self._cost_calculator.calculate(
            portfolio_id=portfolio_id,
            trades=trades,
            current_prices=current_prices,
        )

        for pos in positions:
            theses = self._theses.get(portfolio_id, [])
            for thesis in theses:
                if thesis.position_id == pos.position_id:
                    object.__setattr__(pos, "thesis", thesis)
                    break

        return positions

    def get_risk(
        self,
        portfolio_id: str,
        current_prices: dict[str, float] | None = None,
        prices_history: dict[str, list[float]] | None = None,
        upcoming_events: dict[str, datetime] | None = None,
    ) -> PortfolioRiskReport:
        """Compute the portfolio risk report (corresponds to GET /portfolios/{id}/risk).

        Args:
            portfolio_id: Identifier of the portfolio.
            current_prices: Optional mapping from symbol to current market price.
            prices_history: Optional historical price series per symbol.
            upcoming_events: Optional mapping from symbol to upcoming event date.

        Returns:
            A PortfolioRiskReport for the current positions.
        """
        positions = self.get_positions(portfolio_id, current_prices)
        return self._risk_engine.calculate(
            portfolio_id=portfolio_id,
            positions=positions,
            prices_history=prices_history,
            upcoming_events=upcoming_events,
        )

    def get_overview(
        self,
        portfolio_id: str,
        current_prices: dict[str, float] | None = None,
        prices_history: dict[str, list[float]] | None = None,
        upcoming_events: dict[str, datetime] | None = None,
    ) -> PortfolioOverview:
        """Return the portfolio overview dashboard (product §8.1).

        Args:
            portfolio_id: Identifier of the portfolio.
            current_prices: Optional mapping from symbol to current market price.
            prices_history: Optional historical price series per symbol.
            upcoming_events: Optional mapping from symbol to upcoming event date.

        Returns:
            A PortfolioOverview populated with positions, risk, and cash data.
        """
        portfolio = self.get_portfolio(portfolio_id)
        positions = self.get_positions(portfolio_id, current_prices)
        risk = self.get_risk(
            portfolio_id, current_prices, prices_history, upcoming_events
        )

        total_mv = sum(p.market_value or 0 for p in positions)
        cumulative_pnl = sum(p.unrealized_pnl or 0 for p in positions)

        industry_exposure: dict[str, float] = {}
        for m in risk.metrics:
            if m.name == "industry_concentration":
                industry_exposure = m.details.get("weights", {})
                break

        style_exposure: dict[str, float] = {}
        for m in risk.metrics:
            if m.name == "style_exposure":
                style_exposure = {
                    "growth": m.details.get("growth_weight", 0),
                    "value": m.details.get("value_weight", 0),
                }
                break

        volatility = None
        max_drawdown = None
        for m in risk.metrics:
            if m.name == "volatility":
                volatility = m.value
            if m.name == "drawdown":
                max_drawdown = m.value

        high_risk_count = sum(
            1 for p in positions if p.health_status
            in (PositionHealthStatus.RISK, PositionHealthStatus.INVALIDATED)
        )

        events_list: list[dict[str, Any]] = []
        if upcoming_events:
            for symbol, event_date in upcoming_events.items():
                events_list.append({
                    "symbol": symbol,
                    "date": event_date,
                    "days_until": (event_date - datetime.now()).days,
                })

        return PortfolioOverview(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.name,
            total_assets=portfolio.cash + total_mv,
            cash=portfolio.cash,
            market_value=total_mv,
            cumulative_pnl=cumulative_pnl,
            portfolio_volatility=volatility,
            max_drawdown=max_drawdown,
            industry_exposure=industry_exposure,
            style_exposure=style_exposure,
            high_risk_count=high_risk_count,
            upcoming_events=events_list,
            position_count=len(positions),
        )

    def get_position_detail(
        self,
        portfolio_id: str,
        position_id: str,
        current_prices: dict[str, float] | None = None,
    ) -> PositionDetail:
        """Return detailed information for a single position (product §8.2).

        Args:
            portfolio_id: Identifier of the portfolio.
            position_id: Identifier of the position.
            current_prices: Optional mapping from symbol to current market price.

        Returns:
            A PositionDetail for the requested position.

        Raises:
            KeyError: If the position is not found in the portfolio.
        """
        positions = self.get_positions(portfolio_id, current_prices)
        position = None
        for p in positions:
            if p.position_id == position_id:
                position = p
                break

        if position is None:
            raise KeyError(f"Position '{position_id}' not found in portfolio '{portfolio_id}'")

        trades = self._trades[portfolio_id]
        trade_history = [
            {
                "trade_id": t.trade_id,
                "side": t.side.value,
                "quantity": t.quantity,
                "price": t.price,
                "amount": t.amount,
                "traded_at": t.traded_at,
                "source": t.source.value,
            }
            for t in trades
            if t.symbol == position.symbol
        ]

        total_mv = sum(p.market_value or 0 for p in positions)
        weight = (
            (position.market_value or 0) / total_mv if total_mv > 0 else None
        )

        return PositionDetail(
            position_id=position.position_id,
            symbol=position.symbol,
            quantity=position.quantity,
            cost_price=position.cost_price,
            cost_amount=position.cost_amount,
            current_price=position.current_price,
            market_value=position.market_value,
            unrealized_pnl=position.unrealized_pnl,
            unrealized_pnl_pct=position.unrealized_pnl_pct,
            industry=position.industry,
            health_status=position.health_status,
            thesis=position.thesis,
            trade_history=trade_history,
            weight=weight,
        )

    def update_thesis(
        self,
        portfolio_id: str,
        position_id: str,
        thesis: str,
        entry_conditions: list[str] | None = None,
        hold_conditions: list[str] | None = None,
        invalidation_conditions: list[str] | None = None,
        target_horizon: list[int] | None = None,
        next_review_at: datetime | None = None,
        status: ThesisStatus = ThesisStatus.THESIS_VALID,
    ) -> PositionThesis:
        """Update the investment thesis for a position (corresponds to PUT /positions/{id}/thesis).

        Each update creates a new version; previous versions are retained for audit.

        Args:
            portfolio_id: Identifier of the portfolio.
            position_id: Identifier of the position.
            thesis: Narrative investment thesis.
            entry_conditions: Conditions that justified entering the position.
            hold_conditions: Conditions required to keep holding the position.
            invalidation_conditions: Conditions that would invalidate the thesis.
            target_horizon: Target review horizons in days.
            next_review_at: Optional next scheduled review timestamp.
            status: Current thesis status.

        Returns:
            The newly created PositionThesis record.
        """
        import uuid

        self._ensure_portfolio(portfolio_id)
        existing = self._theses.get(portfolio_id, [])
        version = len([t for t in existing if t.position_id == position_id]) + 1

        new_thesis = PositionThesis(
            thesis_id=f"th_{uuid.uuid4().hex[:12]}",
            position_id=position_id,
            thesis=thesis,
            entry_conditions=entry_conditions or [],
            hold_conditions=hold_conditions or [],
            invalidation_conditions=invalidation_conditions or [],
            target_horizon=target_horizon or [60, 120],
            next_review_at=next_review_at,
            status=status,
            version=version,
        )
        self._theses.setdefault(portfolio_id, []).append(new_thesis)
        return new_thesis

    def get_thesis_history(
        self,
        portfolio_id: str,
        position_id: str,
    ) -> list[PositionThesis]:
        """Return the version history of investment theses for a position.

        Args:
            portfolio_id: Identifier of the portfolio.
            position_id: Identifier of the position.

        Returns:
            All thesis versions for the position, oldest to newest.
        """
        self._ensure_portfolio(portfolio_id)
        return [
            t for t in self._theses.get(portfolio_id, [])
            if t.position_id == position_id
        ]

    @property
    def importer(self) -> TradeImporter:
        """Expose the internal trade importer (used for broker plugin registration)."""
        return self._importer

    def _ensure_portfolio(self, portfolio_id: str) -> None:
        """Validate that a portfolio exists; raise KeyError otherwise.

        Args:
            portfolio_id: Identifier of the portfolio to validate.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        if portfolio_id not in self._portfolios:
            raise KeyError(f"Portfolio '{portfolio_id}' not found")

    def _append_trades(self, portfolio_id: str, trades: list[Trade]) -> None:
        """Append trades to a portfolio and update derived state.

        Args:
            portfolio_id: Identifier of the portfolio.
            trades: Trades to append.
        """
        self._trades[portfolio_id].extend(trades)
        self._apply_cash_delta(portfolio_id, trades)
        self._invalidate_cache(portfolio_id)

    def _apply_cash_delta(self, portfolio_id: str, trades: list[Trade]) -> None:
        """Adjust portfolio cash by the net cash impact of the given trades.

        Args:
            portfolio_id: Identifier of the portfolio.
            trades: Trades whose cash impact should be applied.
        """
        if not trades:
            return

        delta = sum(_cash_delta(t) for t in trades)
        portfolio = self._portfolios[portfolio_id]
        self._portfolios[portfolio_id] = portfolio.model_copy(
            update={"cash": portfolio.cash + delta}
        )

    def _invalidate_cache(self, portfolio_id: str) -> None:
        """Clear the cached positions for a portfolio after a trade change.

        Args:
            portfolio_id: Identifier of the portfolio whose cache should be cleared.
        """
        self._positions_cache.pop(portfolio_id, None)


def _cash_delta(trade: Trade) -> float:
    """Compute the cash impact of a single trade.

    Args:
        trade: Trade record to evaluate.

    Returns:
        Signed cash delta: negative for buys, positive for sells and dividends.
    """
    if trade.side == TradeSide.BUY:
        return -(trade.quantity * trade.price + trade.fee + trade.tax)
    if trade.side == TradeSide.SELL:
        return trade.quantity * trade.price - trade.fee - trade.tax
    if trade.side == TradeSide.DIVIDEND:
        return trade.quantity * trade.price
    return 0.0
