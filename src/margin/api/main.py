"""FastAPI application factory for the Margin API.

This module constructs and configures the Margin API application. It wires
route handlers, registers dependency overrides for testing, and exposes a
simple health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

from margin.api.dependencies import (
    get_dashboard_services,
    get_monitoring_services,
    get_portfolio_service,
    get_research_service,
    get_strategy_service,
)
from margin.api.metrics import router as metrics_router
from margin.api.middleware import MetricsMiddleware, TraceIdMiddleware
from margin.api.routes.dashboard import router as dashboard_router
from margin.api.routes.health import router as health_router
from margin.api.routes.monitoring import router as monitoring_router
from margin.api.routes.portfolios import router as portfolio_router
from margin.api.routes.research import router as research_router
from margin.api.routes.strategy import router as strategy_router
from margin.core.logging_config import configure_logging
from margin.dashboard.service import DashboardServiceBundle
from margin.holdings_monitoring.service import MonitoringServiceBundle
from margin.portfolio.service import PortfolioService
from margin.research.service import ResearchService
from margin.settings import get_settings
from margin.strategy.service import StrategyService


def create_app(
    portfolio_service: PortfolioService | None = None,
    research_service: ResearchService | None = None,
    strategy_service: StrategyService | None = None,
    dashboard_services: DashboardServiceBundle | None = None,
    monitoring_services: MonitoringServiceBundle | None = None,
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
        dashboard_services: Optional dashboard service bundle to inject in
            place of the default PostgreSQL-backed services.
        monitoring_services: Optional holdings monitoring service bundle to
            inject in place of the default PostgreSQL-backed services.

    Returns:
        FastAPI: The configured API application.
    """
    settings = get_settings()
    configure_logging(log_level=settings.log_level, log_format=settings.log_format)
    application = FastAPI(title="Margin API", version=settings.service_version)
    # TraceIdMiddleware runs first so downstream middleware and routes can read the trace id.
    application.add_middleware(TraceIdMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.include_router(metrics_router)
    application.include_router(health_router)
    application.include_router(portfolio_router)
    application.include_router(research_router)
    application.include_router(strategy_router)
    application.include_router(dashboard_router)
    application.include_router(monitoring_router)

    # Override production dependencies with injected services for testing.
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
    if dashboard_services is not None:
        application.dependency_overrides[get_dashboard_services] = (
            lambda: dashboard_services
        )
    if monitoring_services is not None:
        application.dependency_overrides[get_monitoring_services] = (
            lambda: monitoring_services
        )

    return application


app = create_app()
"""Default Margin API application instance created with production settings."""
