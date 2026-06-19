"""Portfolio repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.portfolio.models import (
    Portfolio,
    PositionThesis,
    TradeSide,
    make_trade,
)
from margin.portfolio.repository import MemoryPortfolioRepository


def test_memory_repository_round_trip():
    """The memory repository must preserve portfolio, trade, and thesis records."""
    repository = MemoryPortfolioRepository()
    portfolio = Portfolio(portfolio_id="pf_1", user_id="user_1", name="Core", cash=1000)
    trade = make_trade(
        portfolio_id=portfolio.portfolio_id,
        symbol="000001.SZ",
        side=TradeSide.BUY,
        quantity=100,
        price=10,
        traded_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    thesis = PositionThesis(
        thesis_id="th_1",
        position_id="pos_1",
        thesis="现金流改善",
        version=1,
    )

    repository.add_portfolio(portfolio)
    repository.add_trades([trade])
    repository.add_thesis(portfolio.portfolio_id, thesis)

    assert repository.get_portfolio(portfolio.portfolio_id) == portfolio
    assert repository.list_portfolios() == [portfolio]
    assert repository.list_trades(portfolio.portfolio_id) == [trade]
    assert repository.list_theses(portfolio.portfolio_id, "pos_1") == [thesis]


def test_memory_repository_updates_cash_without_replacing_history():
    """Updating a portfolio must not alter its immutable trade history."""
    repository = MemoryPortfolioRepository()
    portfolio = Portfolio(portfolio_id="pf_1", user_id="user_1", name="Core", cash=1000)
    repository.add_portfolio(portfolio)
    repository.update_portfolio(portfolio.model_copy(update={"cash": 500}))

    assert repository.get_portfolio("pf_1").cash == 500
    assert repository.list_trades("pf_1") == []
