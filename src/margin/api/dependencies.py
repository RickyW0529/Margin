"""FastAPI dependency providers for the Margin API.

This module contains production-ready dependency callables that FastAPI can
inject into route handlers. The returned services are cached so that each
application instance reuses the same database engine and repository objects.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from margin.core.orchestration_repository import SQLAlchemyOrchestrationRepository
from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.dashboard.repository import SQLAlchemyDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.providers.akshare_provider import AKShareProvider
from margin.data.providers.tushare_provider import TushareProvider
from margin.data.warehouse_repository import SQLAlchemyWarehouseRepository
from margin.evidence.package_builder import EvidencePackageBuilder
from margin.evidence.repository import EvidenceRepository
from margin.news.acquirer import HTTPConnector, SnapshotStore, SourceRegistry
from margin.news.context_bundle import NewsContextBundleBuilder
from margin.news.models import SourceDescriptor, SourceLevel, utc_now
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.refresh_service import NewsRefreshService
from margin.news.repository import NewsRepository
from margin.news.service import NewsService
from margin.news.target_queue import NewsTargetQueue
from margin.news.websearch import WebSearchProvider, WebSearchService
from margin.research.delta_repository import SQLAlchemyResearchDeltaRepository
from margin.research.graph_audit_repository import (
    SQLAlchemyLLMCallAuditRepository,
    SQLAlchemyToolCallAuditRepository,
)
from margin.research.llm import LLMProvider
from margin.research.service import ResearchService
from margin.settings import MarginSettings, get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.provider_config import HealthCheckCallable, ProviderConfigHealthService
from margin.strategy.provider_runtime import (
    ProviderRuntimeFactory,
    ProviderRuntimeResolver,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService
from margin.valuation_discovery.adapters import (
    AIReviewAdapter,
    DataReadinessAdapter,
    NewsRefreshAdapter,
    ResearchContextBuilderAdapter,
    ScopeResolutionAdapter,
    ValuationPublisherAdapter,
)
from margin.valuation_discovery.assessments import EffectiveAssessmentService
from margin.valuation_discovery.news_targets import NewsTargetSelector
from margin.valuation_discovery.orchestrator import (
    ValuationDiscoveryDependencies,
    ValuationDiscoveryOrchestrationRepository,
    ValuationDiscoveryOrchestrator,
    ValuationDiscoveryStepWorker,
)
from margin.valuation_discovery.quant.repository import SQLAlchemyQuantRepository
from margin.valuation_discovery.quant.service import QuantService
from margin.valuation_discovery.quant_adapter import (
    QuantAdapter,
    SQLAlchemyScopeBindingProvider,
    WarehouseFactAdapter,
    build_cross_section_loader,
)
from margin.valuation_discovery.quant_input import QuantInputSnapshotBuilder
from margin.valuation_discovery.repository import SQLAlchemyValuationDiscoveryRepository
from margin.valuation_discovery.service import ValuationDiscoveryService
from margin.vector.indexing_runner import DocumentIndexingRunner
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.providers.rerank import HTTPRerankProvider
from margin.vector.repository import VectorRepository
from margin.vector.retrieval import RetrievalTool


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


def build_data_warehouse_stack(settings: MarginSettings) -> DataWarehouseIngestionStack:
    """Build the data warehouse ingestion stack from centralized settings."""
    engine = build_database_engine(settings)
    return DataWarehouseIngestionStack(
        session_factory=create_session_factory(engine),
        snapshot_root=settings.data_snapshot_root,
        default_provider=(
            "tushare"
            if settings.tushare_token is not None
            and settings.tushare_token.get_secret_value().strip()
            else "akshare"
        ),
    )


def _missing_provider(
    *,
    name: str,
    provider_type: ProviderType,
    message: str,
    capabilities: list[str],
    secret_refs: list[str],
) -> MissingConfiguredProvider:
    """missing provider."""
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
def get_strategy_repository() -> SQLAlchemyStrategyRepository:
    """Return the production PostgreSQL-backed strategy config repository."""
    engine = build_database_engine(get_settings())
    return SQLAlchemyStrategyRepository(create_session_factory(engine))


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
def get_secret_store() -> SecretStore:
    """Return the encrypted provider Secret Store.

    The service fails closed when the master key is not configured. It never
    generates an ephemeral key because doing so would make stored secrets
    undecryptable after process restart.
    """
    settings = get_settings()
    if settings.secret_master_key is None:
        raise RuntimeError("MARGIN_SECRET_MASTER_KEY is not configured")
    engine = build_database_engine(settings)
    repository = SQLAlchemySecretRepository(create_session_factory(engine))
    return SecretStore(
        repository,
        master_key=settings.secret_master_key.get_secret_value(),
        key_version=settings.secret_key_version,
    )


def get_optional_secret_store() -> SecretStore | None:
    """Return Secret Store when decrypt authority is configured.

    Read-only configuration discovery remains available without a master key.
    Secret writes, health checks, and activation continue to depend on
    :func:`get_secret_store` and therefore fail closed.
    """
    try:
        return get_secret_store()
    except RuntimeError:
        return None


@lru_cache
def get_provider_runtime_factory() -> ProviderRuntimeFactory:
    """Return the strict active-config Provider factory used by business runs."""
    return ProviderRuntimeFactory(
        ProviderRuntimeResolver(
            get_strategy_repository(),
            get_secret_store(),
        )
    )


def get_provider_config_health_service(
    repository: Annotated[
        SQLAlchemyStrategyRepository,
        Depends(get_strategy_repository),
    ],
    secret_store: Annotated[SecretStore, Depends(get_secret_store)],
) -> ProviderConfigHealthService:
    """Return provider health service using frozen configs and encrypted secrets."""
    settings = get_settings()
    return ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters=_build_provider_health_adapters(),
        host_allowlists={
            "tushare": {"api.tushare.pro"},
            "tavily": {"api.tavily.com"},
            "tavily_websearch": {"api.tavily.com"},
            "llm": {"api.openai.com", "api.deepseek.com"},
            "openai_llm": {"api.openai.com", "api.deepseek.com"},
            "embedding": {"api.openai.com", "open.bigmodel.cn"},
            "openai_embedding": {"api.openai.com", "open.bigmodel.cn"},
            "rerank": {"api.cohere.com"},
            "http_rerank": {"api.cohere.com"},
        },
        allow_local_development=settings.allow_local_provider_urls,
        resolve_dns=settings.resolve_provider_dns,
    )


def _build_provider_health_adapters() -> dict[str, HealthCheckCallable]:
    """Build real read-only provider health adapters keyed by config name."""

    def tushare_health(config, secret: str) -> None:
        """tushare health."""
        endpoint = config.base_url or config.non_sensitive_config.get("http_url")
        _require_healthy(
            TushareProvider(token=secret, http_url=endpoint).healthcheck()
        )

    def akshare_health(_config, _secret: str) -> None:
        """akshare health."""
        _require_healthy(AKShareProvider().healthcheck())

    def tavily_health(config, secret: str) -> None:
        """tavily health."""
        kwargs: dict[str, Any] = {"api_key": secret}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        _require_healthy(TavilySearchAdapter(**kwargs).healthcheck())

    def llm_health(config, secret: str) -> None:
        """llm health."""
        _require_healthy(
            LLMProvider(
                api_key=secret,
                base_url=config.base_url,
                model=config.model_name,
            ).healthcheck()
        )

    def embedding_health(config, secret: str) -> None:
        """embedding health."""
        dimension = int(
            config.non_sensitive_config.get("dimension", 1536)
        )
        _require_healthy(
            OpenAIEmbeddingProvider(
                api_key=secret,
                base_url=config.base_url,
                model=config.model_name,
                dimension=dimension,
            ).healthcheck()
        )

    def rerank_health(config, secret: str) -> None:
        """rerank health."""
        _require_healthy(
            HTTPRerankProvider(
                api_key=secret,
                base_url=config.base_url,
                model=config.model_name,
            ).healthcheck()
        )

    return {
        "tushare": tushare_health,
        "akshare": akshare_health,
        "tavily": tavily_health,
        "tavily_websearch": tavily_health,
        "llm": llm_health,
        "openai_llm": llm_health,
        "embedding": embedding_health,
        "openai_embedding": embedding_health,
        "rerank": rerank_health,
        "http_rerank": rerank_health,
    }


def _require_healthy(result: HealthCheckResult) -> None:
    """require healthy."""
    if result.status is not ProviderStatus.HEALTHY:
        raise RuntimeError(
            result.message or f"provider health status: {result.status.value}"
        )


def require_local_admin(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> str:
    """Authenticate a local admin mutation and validate its CSRF token."""
    settings = get_settings()
    if settings.admin_api_token is None or settings.csrf_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin API authentication is not configured",
        )
    expected_authorization = (
        f"Bearer {settings.admin_api_token.get_secret_value()}"
    )
    if authorization is None or not hmac.compare_digest(
        authorization,
        expected_authorization,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="local admin authentication required",
        )
    if csrf_token is None or not hmac.compare_digest(
        csrf_token,
        settings.csrf_token.get_secret_value(),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="valid X-CSRF-Token header is required",
        )
    return "local-admin"


def require_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> str:
    """Require a non-empty idempotency key for a mutating request."""
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    return idempotency_key.strip()


@lru_cache
def get_valuation_discovery_service() -> ValuationDiscoveryService:
    """Return the production valuation discovery service.

    Builds the full orchestration pipeline from active versioned Provider
    configurations. Missing mandatory Provider versions fail closed.

    Returns:
        ValuationDiscoveryService: A cached service ready for dependency
        injection.
    """
    settings = get_settings()
    engine = build_database_engine(settings)
    session_factory = create_session_factory(engine)

    orchestration_repository = ValuationDiscoveryOrchestrationRepository(
        SQLAlchemyOrchestrationRepository(session_factory)
    )

    strategy_repository = SQLAlchemyStrategyRepository(session_factory)
    scope_provider = SQLAlchemyScopeBindingProvider(strategy_repository)
    warehouse_repository = SQLAlchemyWarehouseRepository(session_factory)
    warehouse_fact_adapter = WarehouseFactAdapter(warehouse_repository)
    valuation_repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
    snapshot_builder = QuantInputSnapshotBuilder(
        repository=valuation_repository,
        warehouse_repository=warehouse_fact_adapter,
    )
    quant_repository = SQLAlchemyQuantRepository(
        session_factory,
        cross_section_loader=build_cross_section_loader(warehouse_repository),
    )
    quant_service = QuantService(repository=quant_repository)
    quant_adapter = QuantAdapter(
        quant_service=quant_service,
        snapshot_builder=snapshot_builder,
        scope_provider=scope_provider,
        quant_repository=quant_repository,
    )

    news_target_selector = NewsTargetSelector()

    runtime_factory = get_provider_runtime_factory()
    market_runtime = runtime_factory.build_tushare()
    ingestion_stack = DataWarehouseIngestionStack(
        session_factory=session_factory,
        snapshot_root=settings.data_snapshot_root,
        default_provider="tushare",
    )
    data_readiness_service = DataReadinessAdapter(
        warehouse=warehouse_repository,
        ingestion_stack=ingestion_stack,
        provider=market_runtime.adapter.descriptor.name,
    )
    scope_service = ScopeResolutionAdapter(strategy_repository)
    news_service = _build_news_refresh_adapter(
        settings,
        session_factory,
        runtime_factory=runtime_factory,
    )

    indexing_runner = _build_indexing_runner(
        settings,
        session_factory,
        runtime_factory=runtime_factory,
    )

    research_service = _build_research_service(
        session_factory,
        runtime_factory=runtime_factory,
    )
    embedding_provider = runtime_factory.build_embedding().adapter
    vector_repository = VectorRepository(
        session_factory,
        dimension=embedding_provider.dim,
    )
    evidence_repository = EvidenceRepository(session_factory)
    research_context_builder = ResearchContextBuilderAdapter(
        session_factory,
        news_bundle_builder=NewsContextBundleBuilder(
            NewsRepository(session_factory)
        ),
        retrieval_tool=RetrievalTool(
            PersistentEmbeddingPipeline(
                embedding_provider=embedding_provider,
                repository=vector_repository,
            )
        ),
        evidence_package_builder=EvidencePackageBuilder(
            vector_repository,
            evidence_repository,
        ),
        evidence_repository=evidence_repository,
    )
    ai_review_service = AIReviewAdapter(
        research_service,
        session_factory=session_factory,
    )

    assessment_service = EffectiveAssessmentService()
    valuation_publisher = ValuationPublisherAdapter(
        assessment_service=assessment_service,
        review_repository=SQLAlchemyResearchDeltaRepository(session_factory),
        valuation_repository=valuation_repository,
    )

    dependencies = ValuationDiscoveryDependencies(
        repository=orchestration_repository,
        data_readiness_service=data_readiness_service,
        scope_service=scope_service,
        quant_service=quant_adapter,
        news_target_selector=news_target_selector,
        news_service=news_service,
        indexing_runner=indexing_runner,
        research_context_builder=research_context_builder,
        ai_review_service=ai_review_service,
        valuation_publisher=valuation_publisher,
    )
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    return ValuationDiscoveryService(orchestrator)


def get_valuation_discovery_service_for_api() -> ValuationDiscoveryService:
    """Return valuation discovery service or a typed API configuration error."""
    try:
        return get_valuation_discovery_service()
    except (LookupError, RuntimeError) as exc:
        message = str(exc)
        if _is_runtime_configuration_error(message):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "service_not_configured",
                    "message": message,
                },
            ) from exc
        raise


def _is_runtime_configuration_error(message: str) -> bool:
    """Return true for expected runtime provider configuration gaps."""
    return any(
        marker in message
        for marker in (
            "active provider config not found",
            "active provider secret not configured",
            "active provider references inactive secret",
            "provider secret not configured",
        )
    )


@lru_cache
def get_valuation_discovery_step_worker() -> ValuationDiscoveryStepWorker:
    """Return the background worker for durable valuation-discovery steps."""
    service = get_valuation_discovery_service()
    return service.create_step_worker(
        worker_id=f"{get_settings().service_name}-valuation-discovery",
    )


def _build_news_refresh_adapter(
    settings: MarginSettings,
    session_factory: Any,
    *,
    runtime_factory: ProviderRuntimeFactory,
) -> NewsRefreshAdapter:
    """Build news refresh from the active frozen WebSearch configuration.

    Args:
        settings: Application settings.
        session_factory: SQLAlchemy session factory.

    Returns:
        A configured ``NewsRefreshAdapter``.
    """
    tavily_adapter = runtime_factory.build_websearch().adapter
    repository = NewsRepository(session_factory)
    provider = WebSearchProvider(
        name="tavily_websearch",
        search_func=tavily_adapter.search,
    )
    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(
            name="websearch",
            source_type="websearch",
            default_level=SourceLevel.L4,
            requires_auth=False,
        ),
        HTTPConnector("websearch"),
    )
    websearch_service = WebSearchService(
        provider=provider,
        registry=registry,
        snapshot_store=SnapshotStore(
            base_dir=settings.data_snapshot_root.parent / "news"
        ),
        repository=repository,
    )
    refresh_service = NewsRefreshService(
        queue=NewsTargetQueue(repository),
        websearch_provider=websearch_service,
        repository=repository,
    )
    return NewsRefreshAdapter(refresh_service)


def _build_indexing_runner(
    settings: MarginSettings,
    session_factory: Any,
    *,
    runtime_factory: ProviderRuntimeFactory,
) -> DocumentIndexingRunner:
    """Build a document indexing runner for the orchestrator.

    Args:
        settings: Application settings.
        session_factory: SQLAlchemy session factory.

    Returns:
        A ``DocumentIndexingRunner`` wired with a real active embedding Provider.
    """
    embedding_provider = runtime_factory.build_embedding().adapter
    return DocumentIndexingRunner(
        news_repository=NewsRepository(session_factory),
        vector_repository=VectorRepository(
            session_factory,
            dimension=embedding_provider.dim,
        ),
        embedding_provider=embedding_provider,
    )


def _build_research_service(
    session_factory: Any,
    *,
    runtime_factory: ProviderRuntimeFactory,
) -> ResearchService:
    """Build a research service for AI delta review.

    Args:
        session_factory: SQLAlchemy session factory.

    Returns:
        A ``ResearchService`` with configured LLM and graph audit repositories.
    """
    llm_provider = runtime_factory.build_llm().adapter
    return ResearchService(
        llm_provider=llm_provider,
        session_factory=session_factory,
        v02_llm_audit_repository=SQLAlchemyLLMCallAuditRepository(
            session_factory
        ),
        v02_tool_audit_repository=SQLAlchemyToolCallAuditRepository(
            session_factory
        ),
    )


@lru_cache
def get_news_service() -> NewsService:
    """Return production target-driven news refresh service.

    The dependency fails closed if Tavily/WebSearch credentials are absent; it does not
    silently accept refresh requests without an external provider.
    """
    settings = get_settings()
    try:
        tavily_adapter = get_provider_runtime_factory().build_websearch().adapter
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="active websearch provider is not available",
        ) from exc
    engine = build_database_engine(settings)
    session_factory = create_session_factory(engine)
    repository = NewsRepository(session_factory)
    provider = WebSearchProvider(
        name="tavily_websearch",
        search_func=tavily_adapter.search,
    )
    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(
            name="websearch",
            source_type="websearch",
            default_level=SourceLevel.L4,
            requires_auth=False,
        ),
        HTTPConnector("websearch"),
    )
    websearch_service = WebSearchService(
        provider=provider,
        registry=registry,
        snapshot_store=SnapshotStore(base_dir=settings.data_snapshot_root.parent / "news"),
        repository=repository,
    )
    refresh_service = NewsRefreshService(
        queue=NewsTargetQueue(repository),
        websearch_provider=websearch_service,
        repository=repository,
    )
    return NewsService(repository=repository, refresh_service=refresh_service)


@lru_cache
def get_data_warehouse_stack() -> DataWarehouseIngestionStack:
    """Return the production data warehouse ingestion stack."""
    return build_data_warehouse_stack(get_settings())


@lru_cache
def get_dashboard_services() -> DashboardServiceBundle:
    """Return production dashboard services backed by PostgreSQL."""
    engine = build_database_engine(get_settings())
    session_factory = create_session_factory(engine)
    dashboard_repository = SQLAlchemyDashboardRepository(session_factory)
    settings = get_settings()
    return DashboardServiceBundle.from_repositories(
        dashboard_repository=dashboard_repository,
        providers=build_provider_status_providers(settings),
    )
