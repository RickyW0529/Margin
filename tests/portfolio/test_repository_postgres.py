"""PostgreSQL portfolio repository integration tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.portfolio.db_models import PortfolioRow, PositionThesisRow, TradeRow
from margin.portfolio.models import (
    Portfolio,
    PositionThesis,
    TradeSide,
    make_trade,
)
from margin.portfolio.repository import SQLAlchemyPortfolioRepository
from margin.portfolio.service import PortfolioService
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def repository(database_url):
    """Provision a clean PostgreSQL schema for a single integration test.

    Creates all portfolio tables, removes stale rows, and yields a repository together
    with the session factory that backs it. Tables are dropped and the engine is
    disposed when the test finishes.

    Args:
        database_url: PostgreSQL connection URL supplied by the test environment.

    Yields:
        A tuple containing the SQLAlchemyPortfolioRepository under test and the
        session factory used to open transactions.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(PositionThesisRow).delete()
        session.query(TradeRow).delete()
        session.query(PortfolioRow).delete()
    yield SQLAlchemyPortfolioRepository(session_factory), session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_postgres_repository_survives_new_session(repository):
    """Persisted portfolio records must be readable through a fresh session."""
    repo, session_factory = repository
    portfolio = Portfolio(portfolio_id="pf_pg", user_id="user_1", name="Postgres", cash=2000)
    trade = make_trade(
        portfolio_id=portfolio.portfolio_id,
        symbol="600000.SH",
        side=TradeSide.BUY,
        quantity=200,
        price=8,
        traded_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    first = PositionThesis(
        thesis_id="th_1",
        position_id="pos_1",
        thesis="初始逻辑",
        version=1,
    )
    second = first.model_copy(
        update={"thesis_id": "th_2", "thesis": "更新逻辑", "version": 2}
    )

    repo.add_portfolio(portfolio)
    repo.add_trades([trade])
    repo.add_thesis(portfolio.portfolio_id, first)
    repo.add_thesis(portfolio.portfolio_id, second)

    fresh = SQLAlchemyPortfolioRepository(session_factory)
    assert fresh.get_portfolio("pf_pg") == portfolio
    assert fresh.list_trades("pf_pg") == [trade]
    assert [item.version for item in fresh.list_theses("pf_pg", "pos_1")] == [1, 2]


def test_portfolio_service_survives_new_instance(repository):
    """Two service instances must share persisted PostgreSQL state."""
    repo, session_factory = repository
    first_service = PortfolioService(repository=repo)
    portfolio = first_service.create_portfolio("user_1", "Persistent", cash=5000)
    first_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 18, tzinfo=UTC),
    )

    second_service = PortfolioService(
        repository=SQLAlchemyPortfolioRepository(session_factory)
    )

    assert second_service.get_portfolio(portfolio.portfolio_id).name == "Persistent"
    assert len(second_service.get_trades(portfolio.portfolio_id)) == 1
