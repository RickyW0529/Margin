"""FastAPI application factory for the Margin API.

This module constructs and configures the Margin API application. It wires
route handlers, registers dependency overrides for testing, and exposes a
simple health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from margin.api.dependencies import (
    get_portfolio_service,
    get_research_service,
    get_strategy_service,
)
from margin.api.routes.portfolios import router as portfolio_router
from margin.api.routes.research import router as research_router
from margin.api.routes.strategy import router as strategy_router
from margin.portfolio.service import PortfolioService
from margin.research.service import ResearchService
from margin.strategy.service import StrategyService


def create_app(
    portfolio_service: PortfolioService | None = None,
    research_service: ResearchService | None = None,
    strategy_service: StrategyService | None = None,
) -> FastAPI:
    """Create and configure the Margin API application.

    The returned application includes portfolio routes, research routes,
    strategy routes, and a health check. If services are supplied, they
    override the production dependencies so the same application can be
    exercised with fake or test services.

    Args:
        portfolio_service: Optional portfolio service to inject in place of the
            default PostgreSQL-backed service.
        research_service: Optional research service to inject in place of the
            default service.
        strategy_service: Optional strategy service to inject in place of the
            default service.

    Returns:
        FastAPI: The configured API application.
    """
    application = FastAPI(title="Margin API", version="0.1.0")
    application.include_router(portfolio_router)
    application.include_router(research_router)
    application.include_router(strategy_router)

    if portfolio_service is not None:
        application.dependency_overrides[get_portfolio_service] = (
            lambda: portfolio_service
        )
    if research_service is not None:
        application.dependency_overrides[get_research_service] = (
            lambda: research_service
        )
    if strategy_service is not None:
        application.dependency_overrides[get_strategy_service] = (
            lambda: strategy_service
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        """Return a basic health status response."""
        return {"status": "ok"}

    return application


app = create_app()
"""Default Margin API application instance created with production settings."""
