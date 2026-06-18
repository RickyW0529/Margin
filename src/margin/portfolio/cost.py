"""Cost and profit/loss calculation — moving weighted average method.

Corresponds to spec 02 §4 data model and architecture §17 position service architecture.
Corresponds to plan 0202.1: cost and quantity calculation (position cost, market value,
profit/loss).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from margin.portfolio.models import Position, PositionHealthStatus, Trade, TradeSide


def _make_position_id(portfolio_id: str, symbol: str) -> str:
    """Deterministically generate a ``position_id`` from ``portfolio_id`` and ``symbol``.

    The same portfolio-symbol pair always yields the same position ID, making it easy
    to reference positions across repeated queries.

    Args:
        portfolio_id: Portfolio identifier.
        symbol: Trading symbol.

    Returns:
        A stable position ID string prefixed with ``pos_``.
    """
    raw = f"{portfolio_id}:{symbol}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"pos_{h}"


@dataclass
class _CostTracker:
    """Per-symbol cost tracker using the moving weighted average method.

    Attributes:
        symbol: Trading symbol being tracked.
        quantity: Current holding quantity.
        cost_amount: Total cost amount for the current holding.
        realized_pnl: Accumulated realized profit/loss.
        trade_count: Number of trades applied to this tracker.
    """

    symbol: str
    quantity: float = 0.0
    cost_amount: float = 0.0
    realized_pnl: float = 0.0
    trade_count: int = 0

    @property
    def cost_price(self) -> float:
        """Return the moving weighted average cost price.

        Returns:
            The cost price, or ``0.0`` when the current quantity is zero or negative.
        """
        if self.quantity <= 0:
            return 0.0
        return self.cost_amount / self.quantity

    def apply(self, trade: Trade) -> None:
        """Apply a trade and update holding quantity and cost.

        Behavior by side:
            * BUY: increase quantity and cost amount; cost price is updated by weighted
              average.
            * SELL: decrease quantity, transfer cost at the current cost price, and
              calculate realized profit/loss.
            * DIVIDEND: increase realized profit/loss by the dividend amount.
            * SPLIT: adjust quantity by the split ratio.

        Args:
            trade: A ``Trade`` instance to apply.

        Raises:
            ValueError: If a sell quantity exceeds the current holding quantity.
        """
        self.trade_count += 1

        if trade.side == TradeSide.BUY:
            self.cost_amount += trade.quantity * trade.price + trade.fee + trade.tax
            self.quantity += trade.quantity

        elif trade.side == TradeSide.SELL:
            if self.quantity < trade.quantity:
                raise ValueError(
                    f"Sell {trade.quantity} exceeds holding {self.quantity} "
                    f"for {self.symbol}"
                )
            sell_cost = self.cost_price * trade.quantity
            self.quantity -= trade.quantity
            self.cost_amount -= sell_cost
            proceeds = trade.quantity * trade.price - trade.fee - trade.tax
            self.realized_pnl += proceeds - sell_cost

        elif trade.side == TradeSide.DIVIDEND:
            self.realized_pnl += trade.quantity * trade.price

        elif trade.side == TradeSide.SPLIT:
            if trade.price > 0:
                ratio = trade.price
                self.quantity *= ratio
                self.cost_price_const = self.cost_amount / self.quantity if self.quantity else 0


class CostCalculator:
    """Cost calculator — computes position cost and profit/loss from a trade sequence.

    Uses the moving weighted average method (common for A-shares):
        * On buy: new cost = (old cost + buy amount) / (old quantity + buy quantity)
        * On sell: transfer cost at the current cost price and calculate realized PnL
    """

    def calculate(
        self,
        portfolio_id: str,
        trades: list[Trade],
        current_prices: dict[str, float] | None = None,
    ) -> list[Position]:
        """Calculate positions per symbol from a list of trades.

        Args:
            portfolio_id: Portfolio identifier.
            trades: A list of trade records, ideally sorted by time. The method sorts
                them internally by ``traded_at``.
            current_prices: Optional dictionary mapping ``symbol`` to current price,
                used to compute unrealized profit/loss.

        Returns:
            A list of ``Position`` instances with quantity greater than zero.
        """
        sorted_trades = sorted(trades, key=lambda t: t.traded_at)
        trackers: dict[str, _CostTracker] = {}

        for trade in sorted_trades:
            if trade.symbol not in trackers:
                trackers[trade.symbol] = _CostTracker(symbol=trade.symbol)
            trackers[trade.symbol].apply(trade)

        prices = current_prices or {}
        positions: list[Position] = []

        for symbol, tracker in trackers.items():
            if tracker.quantity <= 0:
                continue

            current_price = prices.get(symbol)
            market_value = None
            unrealized_pnl = None
            unrealized_pnl_pct = None
            health_status = PositionHealthStatus.HEALTHY

            if current_price is not None:
                market_value = tracker.quantity * current_price
                unrealized_pnl = market_value - tracker.cost_amount
                if tracker.cost_amount > 0:
                    unrealized_pnl_pct = unrealized_pnl / tracker.cost_amount
            elif current_prices is not None:
                health_status = PositionHealthStatus.DATA_MISSING

            position_id = _make_position_id(portfolio_id, symbol)

            positions.append(
                Position(
                    position_id=position_id,
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                    quantity=tracker.quantity,
                    cost_price=tracker.cost_price,
                    cost_amount=tracker.cost_amount,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    health_status=health_status,
                )
            )

        return positions

    def calculate_realized_pnl(
        self,
        trades: list[Trade],
    ) -> dict[str, float]:
        """Calculate realized profit/loss per symbol.

        Args:
            trades: A list of trade records. The method sorts them internally by
                ``traded_at``.

        Returns:
            A dictionary mapping each symbol with non-zero realized PnL to its value.
        """
        sorted_trades = sorted(trades, key=lambda t: t.traded_at)
        trackers: dict[str, _CostTracker] = {}

        for trade in sorted_trades:
            if trade.symbol not in trackers:
                trackers[trade.symbol] = _CostTracker(symbol=trade.symbol)
            trackers[trade.symbol].apply(trade)

        return {sym: t.realized_pnl for sym, t in trackers.items() if t.realized_pnl != 0}
