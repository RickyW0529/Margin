"""FastAPI dependency providers for the Margin API.

This module contains production-ready dependency callables that FastAPI can
inject into route handlers. The returned services are cached so that each
application instance reuses the same database engine and repository objects.
"""

from __future__ import annotations

import os
from functools import lru_cache

from margin.portfolio.repository import SQLAlchemyPortfolioRepository
from margin.portfolio.service import PortfolioService
from margin.research.llm import LLMProvider
from margin.research.repository import SQLAlchemyResearchRepository
from margin.research.service import ResearchService
from margin.storage.database import (
    create_database_engine,
    create_session_factory,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService


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


@lru_cache
def get_research_service() -> ResearchService:
    """Return the production research service with append-only persistence.

    Returns:
        ResearchService: A cached research service using configured adapters.
    """
    engine = create_database_engine()
    repository = SQLAlchemyResearchRepository(create_session_factory(engine))
    llm_provider = None
    if os.getenv("MARGIN_LLM_API_KEY") and os.getenv("MARGIN_LLM_BASE_URL"):
        llm_provider = LLMProvider()
    return ResearchService(
        llm_provider=llm_provider,
        repository=repository,
    )


@lru_cache
def get_strategy_service() -> StrategyService:
    """Return the production PostgreSQL-backed strategy configuration service.

    Returns:
        StrategyService: A cached strategy service with append-only version
        persistence backed by PostgreSQL.
    """
    engine = create_database_engine()
    repository = SQLAlchemyStrategyRepository(create_session_factory(engine))
    return StrategyService(repository=repository)
