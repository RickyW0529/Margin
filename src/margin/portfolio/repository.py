"""Portfolio persistence repositories.

This module defines the repository protocol consumed by ``PortfolioService`` and
provides both an in-memory implementation for tests and a SQLAlchemy-backed
implementation for PostgreSQL persistence. Repositories handle portfolios,
trades, and versioned investment theses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.portfolio.db_models import PortfolioRow, PositionThesisRow, TradeRow
from margin.portfolio.models import (
    Portfolio,
    PositionThesis,
    ThesisStatus,
    Trade,
    TradeSide,
    TradeSource,
)


class PortfolioRepository(Protocol):
    """Persistence contract consumed by ``PortfolioService``."""

    def add_portfolio(self, portfolio: Portfolio) -> None:
        """Persist a new portfolio.

        Args:
            portfolio: Portfolio domain object to persist.

        Raises:
            ValueError: If a portfolio with the same identifier already exists.
        """
        ...

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        """Retrieve a portfolio by identifier.

        Args:
            portfolio_id: Unique identifier of the portfolio.

        Returns:
            The matching ``Portfolio`` domain object, or ``None`` if not found.
        """
        ...

    def update_portfolio(self, portfolio: Portfolio) -> None:
        """Persist changes to an existing portfolio.

        Args:
            portfolio: Portfolio domain object with updated fields.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        ...

    def add_trades(self, trades: list[Trade]) -> None:
        """Persist a batch of trades.

        Args:
            trades: List of ``Trade`` domain objects to persist.

        Raises:
            KeyError: If any trade references a portfolio that does not exist.
        """
        ...

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        """Return all trades for a portfolio ordered by execution time.

        Args:
            portfolio_id: Identifier of the portfolio whose trades are returned.

        Returns:
            List of ``Trade`` domain objects.
        """
        ...

    def add_thesis(self, portfolio_id: str, thesis: PositionThesis) -> None:
        """Persist a new investment thesis version.

        Args:
            portfolio_id: Identifier of the portfolio that owns the thesis.
            thesis: ``PositionThesis`` domain object to persist.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        ...

    def list_theses(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionThesis]:
        """Return investment thesis versions for a portfolio.

        Args:
            portfolio_id: Identifier of the portfolio whose theses are returned.
            position_id: Optional position identifier to filter results.

        Returns:
            Thesis versions sorted by ``position_id`` and ``version``.
        """
        ...


class MemoryPortfolioRepository:
    """In-memory repository for unit tests and embedded usage.

    Attributes:
        _portfolios: Mapping from portfolio identifier to ``Portfolio`` instance.
        _trades: Mapping from portfolio identifier to list of ``Trade`` instances.
        _theses: Mapping from portfolio identifier to list of ``PositionThesis`` instances.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory stores."""
        self._portfolios: dict[str, Portfolio] = {}
        self._trades: dict[str, list[Trade]] = {}
        self._theses: dict[str, list[PositionThesis]] = {}

    def add_portfolio(self, portfolio: Portfolio) -> None:
        """Persist a new portfolio in memory.

        Args:
            portfolio: Portfolio domain object to persist.

        Raises:
            ValueError: If the portfolio identifier already exists.
        """
        if portfolio.portfolio_id in self._portfolios:
            raise ValueError(f"Portfolio '{portfolio.portfolio_id}' already exists")
        self._portfolios[portfolio.portfolio_id] = portfolio
        self._trades[portfolio.portfolio_id] = []
        self._theses[portfolio.portfolio_id] = []

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        """Retrieve a portfolio by identifier from memory.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            The matching ``Portfolio`` instance, or ``None`` if not found.
        """
        return self._portfolios.get(portfolio_id)

    def update_portfolio(self, portfolio: Portfolio) -> None:
        """Update an existing portfolio in memory.

        Args:
            portfolio: Portfolio domain object with updated fields.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        if portfolio.portfolio_id not in self._portfolios:
            raise KeyError(f"Portfolio '{portfolio.portfolio_id}' not found")
        self._portfolios[portfolio.portfolio_id] = portfolio

    def add_trades(self, trades: list[Trade]) -> None:
        """Persist trades in memory.

        Args:
            trades: List of ``Trade`` instances to append.

        Raises:
            KeyError: If a trade references a portfolio that does not exist.
        """
        for trade in trades:
            if trade.portfolio_id not in self._portfolios:
                raise KeyError(f"Portfolio '{trade.portfolio_id}' not found")
        for trade in trades:
            self._trades[trade.portfolio_id].append(trade)

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        """Return trades for a portfolio from memory.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            Copy of the portfolio's trade list.
        """
        return list(self._trades.get(portfolio_id, []))

    def add_thesis(self, portfolio_id: str, thesis: PositionThesis) -> None:
        """Persist a thesis version in memory.

        Args:
            portfolio_id: Identifier of the portfolio that owns the thesis.
            thesis: ``PositionThesis`` instance to append.

        Raises:
            KeyError: If the portfolio does not exist.
        """
        if portfolio_id not in self._portfolios:
            raise KeyError(f"Portfolio '{portfolio_id}' not found")
        self._theses[portfolio_id].append(thesis)

    def list_theses(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionThesis]:
        """Return thesis versions from memory.

        Args:
            portfolio_id: Identifier of the portfolio.
            position_id: Optional position identifier filter.

        Returns:
            Filtered and sorted thesis versions.
        """
        theses = self._theses.get(portfolio_id, [])
        if position_id is not None:
            theses = [item for item in theses if item.position_id == position_id]
        return sorted(theses, key=lambda item: (item.position_id, item.version))


class SQLAlchemyPortfolioRepository:
    """PostgreSQL repository backed by short SQLAlchemy sessions.

    Attributes:
        _session_factory: Callable that returns a new SQLAlchemy ``Session``.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a session factory.

        Args:
            session_factory: Callable returning a SQLAlchemy ``Session``.
        """
        self._session_factory = session_factory

    def add_portfolio(self, portfolio: Portfolio) -> None:
        """Persist a new portfolio to PostgreSQL.

        Args:
            portfolio: Portfolio domain object to persist.
        """
        with self._session_factory.begin() as session:
            session.add(_portfolio_to_row(portfolio))

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        """Retrieve a portfolio from PostgreSQL.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            The matching ``Portfolio`` domain object, or ``None`` if not found.
        """
        with self._session_factory() as session:
            row = session.get(PortfolioRow, portfolio_id)
            return _portfolio_from_row(row) if row is not None else None

    def update_portfolio(self, portfolio: Portfolio) -> None:
        """Update an existing portfolio in PostgreSQL.

        Args:
            portfolio: Portfolio domain object with updated fields.

        Raises:
            KeyError: If the portfolio row does not exist.
        """
        with self._session_factory.begin() as session:
            row = session.get(PortfolioRow, portfolio.portfolio_id)
            if row is None:
                raise KeyError(f"Portfolio '{portfolio.portfolio_id}' not found")
            row.user_id = portfolio.user_id
            row.name = portfolio.name
            row.cash = portfolio.cash

    def add_trades(self, trades: list[Trade]) -> None:
        """Persist trades to PostgreSQL.

        Args:
            trades: List of ``Trade`` instances to persist.
        """
        if not trades:
            return
        with self._session_factory.begin() as session:
            session.add_all([_trade_to_row(trade) for trade in trades])

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        """Return trades for a portfolio from PostgreSQL.

        Args:
            portfolio_id: Identifier of the portfolio.

        Returns:
            Trades ordered by ``traded_at`` and ``trade_id``.
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(TradeRow)
                .where(TradeRow.portfolio_id == portfolio_id)
                .order_by(TradeRow.traded_at, TradeRow.trade_id)
            ).all()
            return [_trade_from_row(row) for row in rows]

    def add_thesis(self, portfolio_id: str, thesis: PositionThesis) -> None:
        """Persist a thesis version to PostgreSQL.

        Args:
            portfolio_id: Identifier of the portfolio that owns the thesis.
            thesis: ``PositionThesis`` instance to persist.
        """
        with self._session_factory.begin() as session:
            session.add(_thesis_to_row(portfolio_id, thesis))

    def list_theses(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionThesis]:
        """Return thesis versions from PostgreSQL.

        Args:
            portfolio_id: Identifier of the portfolio.
            position_id: Optional position identifier filter.

        Returns:
            Filtered and sorted thesis domain objects.
        """
        statement = select(PositionThesisRow).where(
            PositionThesisRow.portfolio_id == portfolio_id
        )
        if position_id is not None:
            statement = statement.where(PositionThesisRow.position_id == position_id)
        statement = statement.order_by(
            PositionThesisRow.position_id,
            PositionThesisRow.version,
        )
        with self._session_factory() as session:
            return [_thesis_from_row(row) for row in session.scalars(statement).all()]


def _portfolio_to_row(portfolio: Portfolio) -> PortfolioRow:
    """Convert a ``Portfolio`` domain object to a ``PortfolioRow`` ORM instance.

    Args:
        portfolio: Portfolio domain object.

    Returns:
        A populated ``PortfolioRow`` ready for persistence.
    """
    return PortfolioRow(
        portfolio_id=portfolio.portfolio_id,
        user_id=portfolio.user_id,
        name=portfolio.name,
        cash=portfolio.cash,
        created_at=portfolio.created_at,
    )


def _portfolio_from_row(row: PortfolioRow) -> Portfolio:
    """Convert a ``PortfolioRow`` ORM instance to a ``Portfolio`` domain object.

    Args:
        row: Persisted portfolio row.

    Returns:
        A populated ``Portfolio`` domain object.
    """
    return Portfolio(
        portfolio_id=row.portfolio_id,
        user_id=row.user_id,
        name=row.name,
        cash=float(row.cash),
        created_at=row.created_at,
    )


def _trade_to_row(trade: Trade) -> TradeRow:
    """Convert a ``Trade`` domain object to a ``TradeRow`` ORM instance.

    Args:
        trade: Trade domain object.

    Returns:
        A populated ``TradeRow`` ready for persistence.
    """
    return TradeRow(
        trade_id=trade.trade_id,
        portfolio_id=trade.portfolio_id,
        symbol=trade.symbol,
        side=trade.side.value,
        quantity=trade.quantity,
        price=trade.price,
        amount=trade.amount,
        fee=trade.fee,
        tax=trade.tax,
        traded_at=trade.traded_at,
        source=trade.source.value,
        source_ref=trade.source_ref,
        raw_hash=trade.raw_hash,
        imported_at=trade.imported_at,
        note=trade.note,
    )


def _trade_from_row(row: TradeRow) -> Trade:
    """Convert a ``TradeRow`` ORM instance to a ``Trade`` domain object.

    Args:
        row: Persisted trade row.

    Returns:
        A populated ``Trade`` domain object.
    """
    return Trade(
        trade_id=row.trade_id,
        portfolio_id=row.portfolio_id,
        symbol=row.symbol,
        side=TradeSide(row.side),
        quantity=float(row.quantity),
        price=float(row.price),
        amount=float(row.amount),
        fee=float(row.fee),
        tax=float(row.tax),
        traded_at=row.traded_at,
        source=TradeSource(row.source),
        source_ref=row.source_ref,
        raw_hash=row.raw_hash,
        imported_at=row.imported_at,
        note=row.note,
    )


def _thesis_to_row(portfolio_id: str, thesis: PositionThesis) -> PositionThesisRow:
    """Convert a ``PositionThesis`` domain object to a ``PositionThesisRow``.

    Args:
        portfolio_id: Identifier of the portfolio that owns the thesis.
        thesis: Thesis domain object.

    Returns:
        A populated ``PositionThesisRow`` ready for persistence.
    """
    return PositionThesisRow(
        thesis_id=thesis.thesis_id,
        portfolio_id=portfolio_id,
        position_id=thesis.position_id,
        thesis=thesis.thesis,
        entry_conditions=list(thesis.entry_conditions),
        hold_conditions=list(thesis.hold_conditions),
        invalidation_conditions=list(thesis.invalidation_conditions),
        target_horizon=list(thesis.target_horizon),
        next_review_at=thesis.next_review_at,
        status=thesis.status.value,
        version=thesis.version,
        created_at=thesis.created_at,
    )


def _thesis_from_row(row: PositionThesisRow) -> PositionThesis:
    """Convert a ``PositionThesisRow`` ORM instance to a ``PositionThesis``.

    Args:
        row: Persisted thesis row.

    Returns:
        A populated ``PositionThesis`` domain object.
    """
    return PositionThesis(
        thesis_id=row.thesis_id,
        position_id=row.position_id,
        thesis=row.thesis,
        entry_conditions=list(row.entry_conditions),
        hold_conditions=list(row.hold_conditions),
        invalidation_conditions=list(row.invalidation_conditions),
        target_horizon=list(row.target_horizon),
        next_review_at=row.next_review_at,
        status=ThesisStatus(row.status),
        version=row.version,
        created_at=row.created_at,
    )
