"""Tests for PortfolioService and the portfolio dashboard (0203 acceptance)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from margin.portfolio.importer import ImportValidationError
from margin.portfolio.service import PortfolioService


class TestPortfolioCreation:
    """Tests for creating and retrieving portfolios."""

    def test_create_portfolio(self):
        """Verify that a portfolio is created with the given user, name, and cash."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "我的组合", cash=100000)
        assert pf.user_id == "user_001"
        assert pf.name == "我的组合"
        assert pf.cash == 100000

    def test_get_portfolio_not_found(self):
        """Verify that retrieving a missing portfolio raises a KeyError."""
        service = PortfolioService()
        with pytest.raises(KeyError):
            service.get_portfolio("nonexistent")


class TestAddTrade:
    """Tests for adding trades and updating portfolio cash."""

    def test_add_trade(self):
        """Verify that add_trade creates a trade with the expected symbol and quantity."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        trade = service.add_trade(
            pf.portfolio_id, "000001.SZ", "buy", 1000, 10.5,
            datetime(2026, 6, 17),
        )
        assert trade.symbol == "000001.SZ"
        assert trade.quantity == 1000

    def test_add_trade_updates_cash(self):
        """Verify that buy and sell trades correctly update the portfolio cash balance."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test", cash=10_000)

        service.add_trade(
            pf.portfolio_id,
            "000001.SZ",
            "buy",
            100,
            10.0,
            datetime(2026, 6, 17),
            fee=5.0,
            tax=1.0,
        )
        assert service.get_portfolio(pf.portfolio_id).cash == pytest.approx(8_994.0)

        service.add_trade(
            pf.portfolio_id,
            "000001.SZ",
            "sell",
            50,
            12.0,
            datetime(2026, 6, 18),
            fee=2.0,
            tax=1.0,
        )
        assert service.get_portfolio(pf.portfolio_id).cash == pytest.approx(9_591.0)

    def test_add_trade_portfolio_not_found(self):
        """Verify that adding a trade to a missing portfolio raises a KeyError."""
        service = PortfolioService()
        with pytest.raises(KeyError):
            service.add_trade("nope", "000001.SZ", "buy", 100, 10, datetime(2026, 6, 17))

    def test_get_trades(self):
        """Verify that get_trades returns all trades stored for a portfolio."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 100, 10, datetime(2026, 6, 17))
        service.add_trade(pf.portfolio_id, "600000.SH", "buy", 200, 8, datetime(2026, 6, 17))
        trades = service.get_trades(pf.portfolio_id)
        assert len(trades) == 2


class TestImportCSV:
    """Tests for CSV import through the service layer."""

    def test_import_csv(self):
        """Verify that a valid CSV import stores all trades and returns a record."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")

        content = (
            "symbol,side,quantity,price,traded_at,fee,tax\n"
            "000001.SZ,buy,1000,10.5,2026-06-17,5,3\n"
            "600000.SH,buy,500,8.0,2026-06-17,0,0\n"
        )
        trades, record = service.import_csv(pf.portfolio_id, content)

        assert len(trades) == 2
        assert record.trade_count == 2
        assert record.rejected_count == 0

        stored = service.get_trades(pf.portfolio_id)
        assert len(stored) == 2

    def test_import_csv_with_errors_rejects_all_rows_without_writing(self):
        """Verify that a CSV with errors rejects all rows and writes nothing to the portfolio."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")

        content = (
            "symbol,side,quantity,price,traded_at,fee,tax\n"
            "000001.SZ,buy,1000,10.5,2026-06-17,5,3\n"
            ",buy,500,8.0,2026-06-17,0,0\n"
        )

        with pytest.raises(ImportValidationError) as exc_info:
            service.import_csv(pf.portfolio_id, content)

        assert exc_info.value.record is not None
        assert exc_info.value.record.rejected_count == 1
        assert service.get_trades(pf.portfolio_id) == []


class TestGetPositions:
    """Tests for calculating current positions after buys and sells."""

    def test_positions_after_buys(self):
        """Verify that positions reflect current prices and unrealized P&L after buys."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))
        service.add_trade(pf.portfolio_id, "600000.SH", "buy", 500, 8.0, datetime(2026, 6, 10))

        positions = service.get_positions(
            pf.portfolio_id,
            current_prices={"000001.SZ": 11.0, "600000.SH": 9.0},
        )

        assert len(positions) == 2
        pos_map = {p.symbol: p for p in positions}
        assert pos_map["000001.SZ"].quantity == 1000
        assert pos_map["000001.SZ"].current_price == 11.0
        assert pos_map["000001.SZ"].unrealized_pnl == 1000.0

    def test_positions_after_sell(self):
        """Verify that a partial sell reduces the position quantity."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))
        service.add_trade(pf.portfolio_id, "000001.SZ", "sell", 400, 11.0, datetime(2026, 6, 10))

        positions = service.get_positions(pf.portfolio_id)
        assert len(positions) == 1
        assert positions[0].quantity == 600


class TestGetRisk:
    """Tests for generating portfolio risk reports."""

    def test_risk_report(self):
        """Verify that get_risk returns a report with total value and eight metrics."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))
        service.add_trade(pf.portfolio_id, "600000.SH", "buy", 500, 8.0, datetime(2026, 6, 1))

        risk = service.get_risk(
            pf.portfolio_id,
            current_prices={"000001.SZ": 11.0, "600000.SH": 9.0},
        )

        assert risk.portfolio_id == pf.portfolio_id
        assert risk.total_value == 1000 * 11.0 + 500 * 9.0
        assert len(risk.metrics) == 8

    def test_risk_breach_detected(self):
        """Verify that a concentrated position triggers a single-position breach."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))

        risk = service.get_risk(
            pf.portfolio_id,
            current_prices={"000001.SZ": 11.0},
        )

        single = next(m for m in risk.metrics if m.name == "single_position")
        assert single.value == 1.0
        assert single.breached is True
        assert risk.has_breach is True


class TestGetOverview:
    """Tests for the portfolio overview summary."""

    def test_overview_basic(self):
        """Verify that the overview reflects cash, market value, P&L, and position count."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "我的组合", cash=50000)
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))
        service.add_trade(pf.portfolio_id, "600000.SH", "buy", 500, 8.0, datetime(2026, 6, 1))

        overview = service.get_overview(
            pf.portfolio_id,
            current_prices={"000001.SZ": 11.0, "600000.SH": 9.0},
        )

        assert overview.portfolio_name == "我的组合"
        assert overview.cash == pytest.approx(36_000)
        assert overview.market_value == 1000 * 11.0 + 500 * 9.0
        assert overview.total_assets == pytest.approx(36_000 + overview.market_value)
        assert overview.cumulative_pnl == pytest.approx(1500.0)
        assert overview.position_count == 2

    def test_overview_with_events(self):
        """Verify that upcoming events are included in the overview."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 100, 10.0, datetime(2026, 6, 1))

        event_date = datetime.now() + timedelta(days=15)
        overview = service.get_overview(
            pf.portfolio_id,
            current_prices={"000001.SZ": 11.0},
            upcoming_events={"000001.SZ": event_date},
        )

        assert len(overview.upcoming_events) == 1
        assert overview.upcoming_events[0]["symbol"] == "000001.SZ"

    def test_overview_empty_portfolio(self):
        """Verify that an empty portfolio still returns a consistent overview."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "empty", cash=100000)

        overview = service.get_overview(pf.portfolio_id)
        assert overview.market_value == 0.0
        assert overview.total_assets == 100000
        assert overview.position_count == 0


class TestPositionDetail:
    """Tests for per-position detail including trade history."""

    def test_position_detail(self):
        """Verify that position detail aggregates trades and computes weight."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 1000, 10.0, datetime(2026, 6, 1))
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 500, 12.0, datetime(2026, 6, 10))

        positions = service.get_positions(pf.portfolio_id)
        detail = service.get_position_detail(
            pf.portfolio_id,
            positions[0].position_id,
            current_prices={"000001.SZ": 11.0},
        )

        assert detail.symbol == "000001.SZ"
        assert detail.quantity == 1500
        assert detail.cost_price == pytest.approx(10.6667, rel=0.01)
        assert len(detail.trade_history) == 2
        assert detail.trade_history[0]["side"] == "buy"
        assert detail.weight is not None

    def test_position_detail_not_found(self):
        """Verify that requesting an unknown position detail raises a KeyError."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        with pytest.raises(KeyError):
            service.get_position_detail(pf.portfolio_id, "nonexistent")


class TestThesis:
    """Tests for investment thesis creation and versioning."""

    def test_update_thesis(self):
        """Verify that update_thesis stores the thesis text and entry conditions."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 100, 10.0, datetime(2026, 6, 1))
        positions = service.get_positions(pf.portfolio_id)

        thesis = service.update_thesis(
            pf.portfolio_id,
            positions[0].position_id,
            thesis="现金流改善与估值修复",
            entry_conditions=["ROE > 10%"],
            invalidation_conditions=["现金流连续两季恶化"],
            target_horizon=[60, 120],
        )

        assert thesis.thesis == "现金流改善与估值修复"
        assert thesis.version == 1
        assert "ROE > 10%" in thesis.entry_conditions

    def test_thesis_versioning(self):
        """Verify that updating a thesis twice creates two sequential versions."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(pf.portfolio_id, "000001.SZ", "buy", 100, 10.0, datetime(2026, 6, 1))
        positions = service.get_positions(pf.portfolio_id)
        pos_id = positions[0].position_id

        t1 = service.update_thesis(pf.portfolio_id, pos_id, "thesis v1")
        t2 = service.update_thesis(pf.portfolio_id, pos_id, "thesis v2")

        assert t1.version == 1
        assert t2.version == 2

        history = service.get_thesis_history(pf.portfolio_id, pos_id)
        assert len(history) == 2
        assert history[0].thesis == "thesis v1"
        assert history[1].thesis == "thesis v2"

    def test_positions_attach_latest_thesis_version(self):
        """Position views must expose the latest thesis, not the first version."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        service.add_trade(
            pf.portfolio_id,
            "000001.SZ",
            "buy",
            100,
            10.0,
            datetime(2026, 6, 1),
        )
        position_id = service.get_positions(pf.portfolio_id)[0].position_id
        service.update_thesis(pf.portfolio_id, position_id, "thesis v1")
        service.update_thesis(pf.portfolio_id, position_id, "thesis v2")

        position = service.get_positions(pf.portfolio_id)[0]

        assert position.thesis is not None
        assert position.thesis.version == 2
        assert position.thesis.thesis == "thesis v2"


class TestNoAutoTrade:
    """Tests confirming the system does not perform or store real trading credentials."""

    def test_no_broker_credentials_stored(self):
        """Verify that newly created portfolios do not hold broker credentials."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        assert not hasattr(pf, "broker_password")
        assert not hasattr(pf, "broker_account")

    def test_trade_source_only_import(self):
        """Verify that trades created via the service are recorded as import sources only."""
        service = PortfolioService()
        pf = service.create_portfolio("user_001", "test")
        trade = service.add_trade(
            pf.portfolio_id, "000001.SZ", "buy", 100, 10.0, datetime(2026, 6, 17)
        )
        assert trade.source.value in ("manual", "csv", "excel", "broker_plugin")
