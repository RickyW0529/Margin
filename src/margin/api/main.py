"""FastAPI application factory for the Margin API.

This module constructs and configures the Margin API application. It wires
route handlers, registers dependency overrides for testing, and exposes a
simple health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from margin.api.dependencies import get_portfolio_service
from margin.api.routes.portfolios import router as portfolio_router
from margin.portfolio.service import PortfolioService


def create_app(portfolio_service: PortfolioService | None = None) -> FastAPI:
    """Create and configure the Margin API application.

    The returned application includes portfolio routes and a health check. If
    a portfolio service is supplied, it overrides the production dependency so
    the same application can be exercised with fake or test services.

    Args:
        portfolio_service: Optional portfolio service to inject in place of the
            default PostgreSQL-backed service. Useful for tests and local
            development.

    Returns:
        FastAPI: The configured Margin API application.
    """
    application = FastAPI(title="Margin API", version="0.1.0")
    application.include_router(portfolio_router)

    if portfolio_service is not None:
        application.dependency_overrides[get_portfolio_service] = (
            lambda: portfolio_service
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        """Return a basic health status response.

        Returns:
            dict[str, str]: A mapping with a single ``status`` key set to
            ``"ok"``.
        """
        return {"status": "ok"}

    return application


app = create_app()
"""Default Margin API application instance created with production settings."""
