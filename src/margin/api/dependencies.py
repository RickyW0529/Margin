"""FastAPI dependency providers for the Margin API.

This module contains production-ready dependency callables that FastAPI can
inject into route handlers. The returned services are cached so that each
application instance reuses the same database engine and repository objects.
"""

from __future__ import annotations

from functools import lru_cache

from margin.portfolio.repository import SQLAlchemyPortfolioRepository
from margin.portfolio.service import PortfolioService
from margin.storage.database import (
    create_database_engine,
    create_session_factory,
)


@lru_cache
def get_portfolio_service() -> PortfolioService:
    """Return the production PostgreSQL-backed portfolio service.

    This dependency is cached per process. It builds the SQLAlchemy engine,
    creates a session factory bound to that engine, and initialises the
    repository and service layers used by all portfolio routes.

    Returns:
        PortfolioService: The cached portfolio service ready for dependency
        injection.
    """
    engine = create_database_engine()
    repository = SQLAlchemyPortfolioRepository(create_session_factory(engine))
    return PortfolioService(repository=repository)
