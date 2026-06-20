"""FastAPI dependency providers for the Margin API.

This module contains production-ready dependency callables that FastAPI can
inject into route handlers. The returned services are cached so that each
application instance reuses the same database engine and repository objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from margin.core.audit_repository import SQLAlchemyAuditRepository
from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.dashboard.repository import SQLAlchemyDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.holdings_monitoring.repository import SQLAlchemyMonitoringRepository
from margin.holdings_monitoring.service import MonitoringServiceBundle
from margin.news.models import utc_now
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.repository import NewsRepository
from margin.portfolio.repository import SQLAlchemyPortfolioRepository
from margin.portfolio.service import PortfolioService
from margin.research.llm import LLMProvider
from margin.research.production_tools import build_production_tool_registry
from margin.research.repository import SQLAlchemyResearchRepository
from margin.research.service import ResearchService
from margin.settings import MarginSettings, get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.providers.rerank import HTTPRerankProvider
from margin.vector.repository import VectorRepository


@dataclass(frozen=True)
class MissingConfiguredProvider:
    """Provider-status placeholder for an external provider missing configuration."""

    descriptor: ProviderDescriptor
    message: str

    def healthcheck(self) -> HealthCheckResult:
        """Return a degraded status without attempting a network call."""
        return HealthCheckResult(
            provider_name=self.descriptor.name,
            status=ProviderStatus.DEGRADED,
            checked_at=utc_now(),
            message=self.message,
        )


def build_database_engine(settings: MarginSettings):
    """Build the database engine from centralized application settings."""
    return create_database_engine(
        DatabaseSettings(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
        )
    )


def build_llm_provider(settings: MarginSettings) -> LLMProvider | None:
    """Build the configured OpenAI-compatible LLM provider."""
    if settings.llm_api_key is None or settings.llm_base_url is None:
        return None
    api_key = settings.llm_api_key.get_secret_value().strip()
    if not api_key:
        return None
    return LLMProvider(
        api_key=api_key,
        base_url=str(settings.llm_base_url),
        model=settings.llm_model,
    )


def build_embedding_provider(
    settings: MarginSettings,
) -> OpenAIEmbeddingProvider | None:
    """Build the configured OpenAI-compatible embedding provider."""
    if settings.embedding_api_key is None or settings.embedding_base_url is None:
        return None
    api_key = settings.embedding_api_key.get_secret_value().strip()
    if not api_key:
        return None
    return OpenAIEmbeddingProvider(
        api_key=api_key,
        base_url=str(settings.embedding_base_url),
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )


def build_websearch_provider(settings: MarginSettings) -> TavilySearchAdapter | None:
    """Build the configured Tavily WebSearch provider."""
    if settings.websearch_api_key is None:
        return None
    api_key = settings.websearch_api_key.get_secret_value().strip()
    if not api_key:
        return None
    return TavilySearchAdapter(api_key=api_key)


def build_rerank_provider(settings: MarginSettings) -> HTTPRerankProvider | None:
    """Build the configured HTTP rerank provider."""
    if settings.rerank_api_key is None or settings.rerank_base_url is None:
        return None
    api_key = settings.rerank_api_key.get_secret_value().strip()
    if not api_key:
        return None
    return HTTPRerankProvider(
        api_key=api_key,
        base_url=str(settings.rerank_base_url),
        model=settings.rerank_model,
    )


def _missing_provider(
    *,
    name: str,
    provider_type: ProviderType,
    message: str,
    capabilities: list[str],
    secret_refs: list[str],
) -> MissingConfiguredProvider:
    return MissingConfiguredProvider(
        descriptor=ProviderDescriptor(
            name=name,
            version="unconfigured",
            provider_type=provider_type,
            capabilities=capabilities,
            secret_refs=secret_refs,
            config={},
        ),
        message=message,
    )


def build_provider_status_providers(settings: MarginSettings) -> list[Any]:
    """Build all providers surfaced by the dashboard status endpoint.

    Missing external integrations are represented as degraded placeholders so
    the frontend shows explicit gaps instead of silently omitting them.
    """
    llm_provider = build_llm_provider(settings) or _missing_provider(
        name="openai_llm",
        provider_type=ProviderType.LLM,
        capabilities=["complete", "complete_structured"],
        secret_refs=["MARGIN_LLM_API_KEY"],
        message="MARGIN_LLM_API_KEY or MARGIN_LLM_BASE_URL not configured",
    )
    embedding_provider = build_embedding_provider(settings) or _missing_provider(
        name="openai_embedding",
        provider_type=ProviderType.EMBEDDING,
        capabilities=["embed", "embed_batch"],
        secret_refs=["MARGIN_EMBEDDING_API_KEY"],
        message="MARGIN_EMBEDDING_API_KEY or MARGIN_EMBEDDING_BASE_URL not configured",
    )
    websearch_provider = build_websearch_provider(settings) or _missing_provider(
        name="tavily_websearch",
        provider_type=ProviderType.WEB_SEARCH,
        capabilities=["search"],
        secret_refs=["MARGIN_WEBSEARCH_API_KEY"],
        message="MARGIN_WEBSEARCH_API_KEY not configured",
    )
    rerank_provider = build_rerank_provider(settings) or _missing_provider(
        name="http_rerank",
        provider_type=ProviderType.RERANK,
        capabilities=["rerank"],
        secret_refs=["MARGIN_RERANK_API_KEY"],
        message="MARGIN_RERANK_API_KEY or MARGIN_RERANK_BASE_URL not configured",
    )
    return [
        llm_provider,
        embedding_provider,
        websearch_provider,
        rerank_provider,
    ]


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
    engine = build_database_engine(get_settings())
    repository = SQLAlchemyPortfolioRepository(create_session_factory(engine))
    return PortfolioService(repository=repository)


@lru_cache
def get_research_service() -> ResearchService:
    """Return the production research service with append-only persistence.

    Returns:
        ResearchService: A cached research service using configured adapters.
    """
    engine = build_database_engine(get_settings())
    session_factory = create_session_factory(engine)
    repository = SQLAlchemyResearchRepository(session_factory)
    settings = get_settings()
    llm_provider = build_llm_provider(settings)
    embedding_provider = build_embedding_provider(settings)
    return ResearchService(
        tool_registry=build_production_tool_registry(
            settings,
            embedding_provider=embedding_provider,
            news_repository=NewsRepository(session_factory),
            vector_repository=VectorRepository(
                session_factory,
                dimension=settings.embedding_dimension,
            ),
        ),
        llm_provider=llm_provider,
        repository=repository,
        audit_repository=SQLAlchemyAuditRepository(session_factory),
    )


@lru_cache
def get_strategy_service() -> StrategyService:
    """Return the production PostgreSQL-backed strategy configuration service.

    Returns:
        StrategyService: A cached strategy service with append-only version
        persistence backed by PostgreSQL.
    """
    engine = build_database_engine(get_settings())
    repository = SQLAlchemyStrategyRepository(create_session_factory(engine))
    return StrategyService(repository=repository)


@lru_cache
def get_dashboard_services() -> DashboardServiceBundle:
    """Return production dashboard services backed by PostgreSQL."""
    engine = build_database_engine(get_settings())
    session_factory = create_session_factory(engine)
    dashboard_repository = SQLAlchemyDashboardRepository(session_factory)
    research_repository = SQLAlchemyResearchRepository(session_factory)
    settings = get_settings()
    llm_provider = build_llm_provider(settings)
    embedding_provider = build_embedding_provider(settings)
    return DashboardServiceBundle.from_repositories(
        dashboard_repository=dashboard_repository,
        research_repository=research_repository,
        research_service=ResearchService(
            tool_registry=build_production_tool_registry(
                settings,
                embedding_provider=embedding_provider,
                news_repository=NewsRepository(session_factory),
                vector_repository=VectorRepository(
                    session_factory,
                    dimension=settings.embedding_dimension,
                ),
            ),
            llm_provider=llm_provider,
            repository=research_repository,
            audit_repository=SQLAlchemyAuditRepository(session_factory),
        ),
        providers=build_provider_status_providers(settings),
    )


@lru_cache
def get_monitoring_services() -> MonitoringServiceBundle:
    """Return production holdings monitoring services backed by PostgreSQL."""
    engine = build_database_engine(get_settings())
    session_factory = create_session_factory(engine)
    portfolio_repository = SQLAlchemyPortfolioRepository(session_factory)
    portfolio_service = PortfolioService(repository=portfolio_repository)
    monitoring_repository = SQLAlchemyMonitoringRepository(session_factory)
    return MonitoringServiceBundle.from_repositories(
        repository=monitoring_repository,
        portfolio_service=portfolio_service,
    )
