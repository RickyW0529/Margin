"""Tests for cost calculation and the portfolio risk engine (0202 acceptance)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from margin.portfolio.cost import CostCalculator
from margin.portfolio.models import Position, PositionHealthStatus, TradeSide, make_trade
from margin.portfolio.risk import PortfolioRiskEngine, PortfolioRiskReport


class TestCostCalculator:
    """Tests for CostCalculator position and P&L calculations."""

    def setup_method(self):
        """Create a fresh CostCalculator instance before each test."""
        self.calc = CostCalculator()

    def _buy(self, symbol, qty, price, date=None):
        """Create a buy trade for use in cost calculation tests.

        Args:
            symbol: Ticker symbol of the security.
            qty: Number of shares purchased.
            price: Execution price per share.
            date: Trade datetime; defaults to 2026-06-17 when omitted.

        Returns:
            A frozen Trade instance representing a buy order.
        """
        return make_trade(
            portfolio_id="pf_1",
            symbol=symbol,
            side=TradeSide.BUY,
            quantity=qty,
            price=price,
            traded_at=date or datetime(2026, 6, 17),
        )

    def _sell(self, symbol, qty, price, date=None):
        """Create a sell trade for use in cost calculation tests.

        Args:
            symbol: Ticker symbol of the security.
            qty: Number of shares sold.
            price: Execution price per share.
            date: Trade datetime; defaults to 2026-06-18 when omitted.

        Returns:
            A frozen Trade instance representing a sell order.
        """
        return make_trade(
            portfolio_id="pf_1",
            symbol=symbol,
            side=TradeSide.SELL,
            quantity=qty,
            price=price,
            traded_at=date or datetime(2026, 6, 18),
        )

    def test_single_buy(self):
        """Verify that a single buy produces one position with the original cost basis."""
        trades = [self._buy("000001.SZ", 1000, 10.0)]
        positions = self.calc.calculate("pf_1", trades)

        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "000001.SZ"
        assert pos.quantity == 1000
        assert pos.cost_price == 10.0
        assert pos.cost_amount == 10000.0

    def test_multiple_buys_weighted_average(self):
        """Verify that multiple buys of the same symbol average the cost price."""
        trades = [
            self._buy("000001.SZ", 100, 10.0, datetime(2026, 6, 1)),
            self._buy("000001.SZ", 100, 12.0, datetime(2026, 6, 10)),
        ]
        positions = self.calc.calculate("pf_1", trades)

        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == 200
        assert pos.cost_price == 11.0
        assert pos.cost_amount == 2200.0

    def test_sell_reduces_quantity(self):
        """Verify that a partial sell reduces the position quantity and preserves cost price."""
        trades = [
            self._buy("000001.SZ", 1000, 10.0, datetime(2026, 6, 1)),
            self._sell("000001.SZ", 400, 11.0, datetime(2026, 6, 10)),
        ]
        positions = self.calc.calculate("pf_1", trades)

        assert len(positions) == 1
        assert positions[0].quantity == 600
        assert positions[0].cost_price == 10.0

    def test_sell_exceeds_holding_raises(self):
        """Verify that selling more shares than held raises a ValueError."""
        trades = [
            self._buy("000001.SZ", 100, 10.0, datetime(2026, 6, 1)),
            self._sell("000001.SZ", 200, 11.0, datetime(2026, 6, 10)),
        ]
        with pytest.raises(ValueError, match="exceeds holding"):
            self.calc.calculate("pf_1", trades)

    def test_full_sell_no_position(self):
        """Verify that selling the entire holding removes the position."""
        trades = [
            self._buy("000001.SZ", 100, 10.0, datetime(2026, 6, 1)),
            self._sell("000001.SZ", 100, 11.0, datetime(2026, 6, 10)),
        ]
        positions = self.calc.calculate("pf_1", trades)
        assert len(positions) == 0

    def test_unrealized_pnl_with_current_price(self):
        """Verify that current prices produce correct market value and unrealized P&L."""
        trades = [self._buy("000001.SZ", 1000, 10.0)]
        positions = self.calc.calculate(
            "pf_1", trades, current_prices={"000001.SZ": 12.0}
        )

        pos = positions[0]
        assert pos.current_price == 12.0
        assert pos.market_value == 12000.0
        assert pos.unrealized_pnl == 2000.0
        assert pos.unrealized_pnl_pct == 0.2

    def test_realized_pnl(self):
        """Verify that realized P&L is calculated from completed sell trades."""
        trades = [
            self._buy("000001.SZ", 1000, 10.0, datetime(2026, 6, 1)),
            self._sell("000001.SZ", 500, 12.0, datetime(2026, 6, 10)),
        ]
        realized = self.calc.calculate_realized_pnl(trades)
        assert realized["000001.SZ"] == pytest.approx(1000.0)

    def test_multiple_symbols(self):
        """Verify that positions are grouped separately for each symbol."""
        trades = [
            self._buy("000001.SZ", 100, 10.0),
            self._buy("600000.SH", 200, 8.0),
        ]
        positions = self.calc.calculate("pf_1", trades)
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"000001.SZ", "600000.SH"}

    def test_fee_included_in_cost(self):
        """Verify that fees and taxes are included in the position cost amount."""
        trades = [
            make_trade(
                portfolio_id="pf_1",
                symbol="000001.SZ",
                side=TradeSide.BUY,
                quantity=100,
                price=10.0,
                traded_at=datetime(2026, 6, 17),
                fee=10.0,
                tax=5.0,
            )
        ]
        positions = self.calc.calculate("pf_1", trades)
        assert positions[0].cost_amount == 100 * 10.0 + 10.0 + 5.0
        assert positions[0].cost_price == 1015.0 / 100

    def test_missing_current_price_marks_position_data_missing(self):
        """Verify that missing market data marks the position health as DATA_MISSING."""
        trades = [
            self._buy("000001.SZ", 100, 10.0),
            self._buy("600000.SH", 100, 8.0),
        ]

        positions = self.calc.calculate(
            "pf_1",
            trades,
            current_prices={"000001.SZ": 11.0},
        )

        pos_map = {p.symbol: p for p in positions}
        assert pos_map["000001.SZ"].health_status == PositionHealthStatus.HEALTHY
        assert pos_map["600000.SH"].health_status == PositionHealthStatus.DATA_MISSING
        assert pos_map["600000.SH"].market_value is None


class TestPortfolioRiskEngine:
    """Tests for PortfolioRiskEngine metric and breach detection logic."""

    def setup_method(self):
        """Create a PortfolioRiskEngine with default concentration limits."""
        self.engine = PortfolioRiskEngine(
            max_single_position=0.10,
            max_industry_exposure=0.30,
        )

    def _make_position(
        self,
        symbol="000001.SZ",
        quantity=1000,
        cost_price=10.0,
        current_price=11.0,
        industry="bank",
        market_value=None,
    ):
        """Build a Position instance for use in risk engine tests.

        Args:
            symbol: Ticker symbol of the position.
            quantity: Number of shares held.
            cost_price: Average cost per share.
            current_price: Current market price per share.
            industry: Industry classification for concentration checks.
            market_value: Optional market value; otherwise derived from quantity
                and current_price.

        Returns:
            A Position object populated with derived market value and unrealized P&L.
        """
        import uuid

        mv = market_value if market_value is not None else quantity * current_price
        return Position(
            position_id=f"pos_{uuid.uuid4().hex[:8]}",
            portfolio_id="pf_1",
            symbol=symbol,
            quantity=quantity,
            cost_price=cost_price,
            cost_amount=quantity * cost_price,
            current_price=current_price,
            market_value=mv,
            unrealized_pnl=mv - quantity * cost_price,
            industry=industry,
        )

    def test_empty_positions(self):
        """Verify that an empty portfolio is flagged as breached."""
        report = self.engine.calculate("pf_1", [])
        assert report.total_value == 0.0
        assert report.has_breach is True

    def test_single_position_risk(self):
        """Verify that a single position breaches the single-position limit."""
        positions = [self._make_position(current_price=10, quantity=1000)]
        report = self.engine.calculate("pf_1", positions)

        single_metric = next(
            m for m in report.metrics if m.name == "single_position"
        )
        assert single_metric.value == 1.0
        assert single_metric.breached is True

    def test_industry_concentration(self):
        """Verify that industry concentration is detected across multiple positions."""
        positions = [
            self._make_position(symbol="000001.SZ", industry="bank", current_price=10),
            self._make_position(symbol="600000.SH", industry="bank", current_price=10),
        ]
        report = self.engine.calculate("pf_1", positions)

        industry_metric = next(
            m for m in report.metrics if m.name == "industry_concentration"
        )
        assert industry_metric.value == 1.0
        assert industry_metric.breached is True

    def test_no_breach_within_limits(self):
        """Verify that positions within limits still compute the single-position metric."""
        positions = [
            self._make_position(symbol="000001.SZ", industry="bank", current_price=10),
            self._make_position(symbol="600000.SH", industry="bank", current_price=10),
            self._make_position(symbol="000002.SZ", industry="tech", current_price=10),
            self._make_position(symbol="000003.SZ", industry="tech", current_price=10),
            self._make_position(symbol="000004.SZ", industry="realestate", current_price=10),
        ]
        report = self.engine.calculate("pf_1", positions)
        single = next(m for m in report.metrics if m.name == "single_position")
        assert single.value == 0.2
        assert single.breached is True

    def test_volatility_with_price_history(self):
        """Verify that volatility is computed when a price history is provided."""
        positions = [self._make_position(symbol="000001.SZ")]
        prices = {"000001.SZ": [10.0, 10.5, 10.2, 10.8, 11.0]}
        report = self.engine.calculate("pf_1", positions, prices_history=prices)

        vol_metric = next(m for m in report.metrics if m.name == "volatility")
        assert vol_metric.value > 0

    def test_drawdown(self):
        """Verify that maximum drawdown is calculated from the price history."""
        positions = [self._make_position(symbol="000001.SZ")]
        prices = {"000001.SZ": [10.0, 12.0, 8.0, 9.0, 11.0]}
        report = self.engine.calculate("pf_1", positions, prices_history=prices)

        dd_metric = next(m for m in report.metrics if m.name == "drawdown")
        assert dd_metric.value > 0
        assert dd_metric.value == pytest.approx(1.0 / 3.0, rel=0.01)

    def test_event_concentration(self):
        """Verify that upcoming events are reflected in event concentration."""
        positions = [
            self._make_position(symbol="000001.SZ"),
            self._make_position(symbol="600000.SH"),
        ]
        events = {
            "000001.SZ": datetime.now() + timedelta(days=10),
        }
        report = self.engine.calculate("pf_1", positions, upcoming_events=events)

        event_metric = next(
            m for m in report.metrics if m.name == "event_concentration"
        )
        assert event_metric.value == 0.5
        assert "000001.SZ" in event_metric.details["symbols_with_events_30d"]

    def test_all_eight_metrics_present(self):
        """Verify that the engine returns all eight expected risk metrics."""
        positions = [self._make_position(symbol="000001.SZ")]
        report = self.engine.calculate("pf_1", positions)

        metric_names = {m.name for m in report.metrics}
        expected = {
            "single_position",
            "industry_concentration",
            "style_exposure",
            "correlation",
            "liquidity",
            "volatility",
            "drawdown",
            "event_concentration",
        }
        assert metric_names == expected

    def test_data_missing_when_no_market_value(self):
        """Verify that positions without market value trigger a data-missing breach."""
        positions = [
            Position(
                position_id="pos_1",
                portfolio_id="pf_1",
                symbol="000001.SZ",
                quantity=100,
                cost_price=10.0,
                cost_amount=1000.0,
                market_value=None,
            )
        ]
        report = self.engine.calculate("pf_1", positions)
        assert report.total_value == 0.0
        assert report.has_breach is True

    def test_partial_market_data_missing_degrades_to_single_position_check(self):
        """Verify that partial missing data disables concentration metrics."""
        positions = [
            self._make_position(symbol="000001.SZ", market_value=1100.0),
            Position(
                position_id="pos_missing",
                portfolio_id="pf_1",
                symbol="600000.SH",
                quantity=100,
                cost_price=8.0,
                cost_amount=800.0,
                market_value=None,
                health_status=PositionHealthStatus.DATA_MISSING,
            ),
        ]

        report = self.engine.calculate("pf_1", positions)
        metric_names = {m.name for m in report.metrics}

        assert "data_missing" in metric_names
        assert "single_position" in metric_names
        assert "industry_concentration" not in metric_names
        assert report.has_breach is True


class TestPortfolioRiskReport:
    """Tests for PortfolioRiskReport breach aggregation."""

    def test_has_breach(self):
        """Verify that a breached metric sets has_breach and appears in breached_metrics."""
        from margin.portfolio.risk import RiskMetric

        report = PortfolioRiskReport(
            portfolio_id="pf_1",
            metrics=[
                RiskMetric(name="test", value=0.5, threshold=0.3, breached=True),
            ],
        )
        assert report.has_breach is True
        assert len(report.breached_metrics) == 1

    def test_no_breach(self):
        """Verify that a non-breached metric leaves has_breach false."""
        from margin.portfolio.risk import RiskMetric

        report = PortfolioRiskReport(
            portfolio_id="pf_1",
            metrics=[
                RiskMetric(name="test", value=0.1, threshold=0.3, breached=False),
            ],
        )
        assert report.has_breach is False
        assert len(report.breached_metrics) == 0
