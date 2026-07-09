"""FastAPI application factory for the Margin API.

This module constructs and configures the Margin API application. It wires
route handlers, registers dependency overrides for testing, and exposes a
simple health check endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from margin.agent_runtime.chat_repository import AgentChatRepository
from margin.agent_runtime.context_store import AgentContextStore
from margin.agent_runtime.schedules import AgentScheduleRepository
from margin.agents.context.repository import ContextRepository
from margin.agents.runtime.service import AgentRuntimeService
from margin.agents.tools.audit import InMemoryToolAuditStore, SQLAlchemyToolAuditStore
from margin.api.dependencies import (
    get_agent_chat_repository,
    get_agent_context_store,
    get_agent_runtime_service,
    get_agent_schedule_repository,
    get_app_container,
    get_backfill_application_service,
    get_company_profile_service,
    get_context_repository,
    get_dashboard_services,
    get_llm_provider_factory,
    get_news_service,
    get_optional_secret_store,
    get_secret_store,
    get_strategy_repository,
    get_strategy_service,
    get_tool_audit_store,
    get_valuation_discovery_service,
    get_valuation_discovery_service_for_api,
)
from margin.api.metrics import router as metrics_router
from margin.api.middleware import MetricsMiddleware, TraceIdMiddleware
from margin.api.routes.agent_runtime import router as agent_runtime_router
from margin.api.routes.backfill import router as backfill_router
from margin.api.routes.context import router as context_router
from margin.api.routes.dashboard import router as dashboard_router
from margin.api.routes.data_sync import router as data_sync_router
from margin.api.routes.freshness import router as freshness_router
from margin.api.routes.health import router as health_router
from margin.api.routes.news import router as news_router
from margin.api.routes.strategy import router as strategy_router
from margin.api.routes.strategy_config import router as strategy_config_router
from margin.api.routes.tool_audit import router as tool_audit_router
from margin.api.routes.valuation_discovery import router as valuation_discovery_router
from margin.core.logging_config import configure_logging
from margin.core.secret_store import SecretStore
from margin.dashboard.service import DashboardServiceBundle
from margin.data.backfill.service import BackfillApplicationService
from margin.news.service import NewsService
from margin.research.llm import LLMProvider
from margin.settings import get_settings
from margin.strategy.service import StrategyService
from margin.valuation_discovery.service import (
    CompanyProfileService,
    ValuationDiscoveryService,
)

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _loopback_origin_aliases(origin: str) -> tuple[str, ...]:
    """Return equivalent local origins for browser dev-server CORS checks.

    Args:
        origin: str: .

    Returns:
        tuple[str, ...]: .
    """
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOOPBACK_HOSTS:
        return ()
    try:
        port = parsed.port
    except ValueError:
        return ()

    port_suffix = f":{port}" if port is not None else ""
    return (
        f"{parsed.scheme}://localhost{port_suffix}",
        f"{parsed.scheme}://127.0.0.1{port_suffix}",
        f"{parsed.scheme}://[::1]{port_suffix}",
    )


def _web_origins_from_setting(web_origin: str) -> list[str]:
    """Parse comma-separated web origins and expand local loopback aliases.

    Args:
        web_origin: str: .

    Returns:
        list[str]: .
    """
    web_origins: list[str] = []
    seen: set[str] = set()

    def add(origin: str) -> None:
        """Process add.

        Args:
            origin: str: .

        Returns:
            None: .
        """
        normalized = origin.strip().rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            web_origins.append(normalized)

    for raw_origin in web_origin.split(","):
        origin = raw_origin.strip().rstrip("/")
        if not origin:
            continue
        add(origin)
        for alias in _loopback_origin_aliases(origin):
            add(alias)
    return web_origins


def create_app(
    strategy_service: StrategyService | None = None,
    strategy_repository: object | None = None,
    secret_store: SecretStore | None = None,
    dashboard_services: DashboardServiceBundle | None = None,
    agent_context_store: AgentContextStore | None = None,
    agent_context_repository: ContextRepository | None = None,
    agent_runtime_service: AgentRuntimeService | None = None,
    llm_provider_factory: Callable[[], LLMProvider] | None = None,
    agent_schedule_repository: AgentScheduleRepository | None = None,
    agent_chat_repository: AgentChatRepository | None = None,
    valuation_discovery_service: ValuationDiscoveryService | None = None,
    news_service: NewsService | None = None,
    company_profile_service: CompanyProfileService | None = None,
    backfill_application_service: BackfillApplicationService | None = None,
    tool_audit_store: InMemoryToolAuditStore | SQLAlchemyToolAuditStore | None = None,
) -> FastAPI:
    """Create and configure the Margin API application.

    Args:
        strategy_service: StrategyService | None: .
        strategy_repository: object | None: .
        secret_store: SecretStore | None: .
        dashboard_services: DashboardServiceBundle | None: .
        agent_context_store: AgentContextStore | None: .
        agent_context_repository: ContextRepository | None: .
        agent_runtime_service: AgentRuntimeService | None: .
        llm_provider_factory: Callable[[], LLMProvider] | None: .
        agent_schedule_repository: AgentScheduleRepository | None: .
        agent_chat_repository: AgentChatRepository | None: .
        valuation_discovery_service: ValuationDiscoveryService | None: .
        news_service: NewsService | None: .
        company_profile_service: CompanyProfileService | None: .
        backfill_application_service: BackfillApplicationService | None: .
        tool_audit_store: InMemoryToolAuditStore | SQLAlchemyToolAuditStore | None: .

    Returns:
        FastAPI: .
    """
    settings = get_settings()
    configure_logging(log_level=settings.log_level, log_format=settings.log_format)
    application = FastAPI(
        title="Margin API",
        version=settings.service_version,
        lifespan=_lifespan,
    )
    # CORS: the Next.js web client is served on a different origin (default
    # http://localhost:3000) and issues authenticated mutating requests. Local
    # browser sessions may use localhost, 127.0.0.1, or ::1 interchangeably.
    web_origins = _web_origins_from_setting(settings.web_origin)
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
    application.include_router(agent_runtime_router)
    application.include_router(context_router)
    application.include_router(dashboard_router)
    application.include_router(valuation_discovery_router)
    application.include_router(news_router)
    application.include_router(data_sync_router)
    application.include_router(freshness_router)
    application.include_router(backfill_router)
    application.include_router(tool_audit_router)

    # Override production dependencies with injected services for testing.
    if strategy_service is not None:
        application.dependency_overrides[get_strategy_service] = lambda: strategy_service
    if strategy_repository is not None:
        application.dependency_overrides[get_strategy_repository] = lambda: strategy_repository
    if secret_store is not None:
        application.dependency_overrides[get_secret_store] = lambda: secret_store
        application.dependency_overrides[get_optional_secret_store] = lambda: secret_store
    if dashboard_services is not None:
        application.dependency_overrides[get_dashboard_services] = lambda: dashboard_services
    if agent_context_store is not None:
        application.dependency_overrides[get_agent_context_store] = lambda: agent_context_store
    if agent_context_repository is not None:
        application.dependency_overrides[get_context_repository] = lambda: agent_context_repository
    if agent_runtime_service is not None:
        application.dependency_overrides[get_agent_runtime_service] = lambda: agent_runtime_service
    if llm_provider_factory is not None:
        application.dependency_overrides[get_llm_provider_factory] = lambda: llm_provider_factory
    if agent_schedule_repository is not None:
        application.dependency_overrides[get_agent_schedule_repository] = lambda: (
            agent_schedule_repository
        )
    if agent_chat_repository is not None:
        application.dependency_overrides[get_agent_chat_repository] = lambda: agent_chat_repository
    if valuation_discovery_service is not None:
        application.dependency_overrides[get_valuation_discovery_service] = lambda: (
            valuation_discovery_service
        )
        application.dependency_overrides[get_valuation_discovery_service_for_api] = lambda: (
            valuation_discovery_service
        )
    if news_service is not None:
        application.dependency_overrides[get_news_service] = lambda: news_service
    if company_profile_service is not None:
        application.dependency_overrides[get_company_profile_service] = lambda: (
            company_profile_service
        )
    if backfill_application_service is not None:
        application.dependency_overrides[get_backfill_application_service] = lambda: (
            backfill_application_service
        )
    if tool_audit_store is not None:
        application.dependency_overrides[get_tool_audit_store] = lambda: tool_audit_store

    return application


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    """Run application startup/shutdown resource management.

    Args:
        _application: FastAPI: .

    Yields:
        Any: .
    """
    yield
    _dispose_app_container()


def _dispose_app_container() -> None:
    """Dispose process-level bootstrap resources on application shutdown.

    Returns:
        None: .
    """
    try:
        get_app_container().dispose()
    finally:
        cache_clear = getattr(get_app_container, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()


app = create_app()
"""Default Margin API application instance created with production settings."""
