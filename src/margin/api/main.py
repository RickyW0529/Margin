"""FastAPI application factory for the Margin API.

This module constructs and configures the Margin API application. It wires
route handlers, registers dependency overrides for testing, and exposes a
simple health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from margin.api.dependencies import (
    get_dashboard_services,
    get_news_service,
    get_optional_secret_store,
    get_secret_store,
    get_strategy_repository,
    get_strategy_service,
    get_valuation_discovery_service,
    get_valuation_discovery_service_for_api,
)
from margin.api.metrics import router as metrics_router
from margin.api.middleware import MetricsMiddleware, TraceIdMiddleware
from margin.api.routes.dashboard import router as dashboard_router
from margin.api.routes.data_sync import router as data_sync_router
from margin.api.routes.health import router as health_router
from margin.api.routes.news import router as news_router
from margin.api.routes.strategy import router as strategy_router
from margin.api.routes.strategy_config import router as strategy_config_router
from margin.api.routes.valuation_discovery import router as valuation_discovery_router
from margin.core.logging_config import configure_logging
from margin.core.secret_store import SecretStore
from margin.dashboard.service import DashboardServiceBundle
from margin.news.service import NewsService
from margin.settings import get_settings
from margin.strategy.service import StrategyService
from margin.valuation_discovery.service import ValuationDiscoveryService


def create_app(
    strategy_service: StrategyService | None = None,
    strategy_repository: object | None = None,
    secret_store: SecretStore | None = None,
    dashboard_services: DashboardServiceBundle | None = None,
    valuation_discovery_service: ValuationDiscoveryService | None = None,
    news_service: NewsService | None = None,
) -> FastAPI:
    """Create and configure the Margin API application.

    The returned application includes research, strategy, valuation discovery,
    news, data sync, dashboard, and health routes. If services are supplied, they
    override the production dependencies so the same application can be
    exercised with fake or test services.

    Args:
        strategy_service: Optional strategy service to inject in place of the
            default service.
        strategy_repository: Optional v0.2 strategy config repository.
        secret_store: Optional encrypted provider Secret Store.
        dashboard_services: Optional dashboard service bundle to inject in
            place of the default PostgreSQL-backed services.
        valuation_discovery_service: Optional valuation discovery service to
            inject in place of the default fail-closed dependency.
        news_service: Optional news service to inject in place of the default
            WebSearch-backed dependency.

    Returns:
        FastAPI: The configured API application.
    """
    settings = get_settings()
    configure_logging(log_level=settings.log_level, log_format=settings.log_format)
    application = FastAPI(title="Margin API", version=settings.service_version)
    # CORS: the Next.js web client is served on a different origin (default
    # http://localhost:3000) and issues authenticated mutating requests.
    web_origins = [
        origin.strip()
        for origin in settings.web_origin.split(",")
        if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Idempotency-Key",
            "X-CSRF-Token",
        ],
        expose_headers=[settings.trace_id_header],
    )
    # TraceIdMiddleware runs first so downstream middleware and routes can read the trace id.
    application.add_middleware(TraceIdMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.include_router(metrics_router)
    application.include_router(health_router)
    application.include_router(strategy_router)
    application.include_router(strategy_config_router)
    application.include_router(dashboard_router)
    application.include_router(valuation_discovery_router)
    application.include_router(news_router)
    application.include_router(data_sync_router)

    # Override production dependencies with injected services for testing.
    if strategy_service is not None:
        application.dependency_overrides[get_strategy_service] = (
            lambda: strategy_service
        )
    if strategy_repository is not None:
        application.dependency_overrides[get_strategy_repository] = (
            lambda: strategy_repository
        )
    if secret_store is not None:
        application.dependency_overrides[get_secret_store] = lambda: secret_store
        application.dependency_overrides[get_optional_secret_store] = (
            lambda: secret_store
        )
    if dashboard_services is not None:
        application.dependency_overrides[get_dashboard_services] = (
            lambda: dashboard_services
        )
    if valuation_discovery_service is not None:
        application.dependency_overrides[get_valuation_discovery_service] = (
            lambda: valuation_discovery_service
        )
        application.dependency_overrides[get_valuation_discovery_service_for_api] = (
            lambda: valuation_discovery_service
        )
    if news_service is not None:
        application.dependency_overrides[get_news_service] = lambda: news_service

    return application


app = create_app()
"""Default Margin API application instance created with production settings."""
