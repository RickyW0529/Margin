"""FastAPI dependency providers for the Margin API.

This module contains production-ready dependency callables that FastAPI can
inject into route handlers. The returned services are cached so that each
application instance reuses the same database engine and repository objects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from margin.agent_runtime.chat_repository import SQLAlchemyAgentChatRepository
from margin.agent_runtime.context_store import SQLAlchemyAgentContextStore
from margin.agent_runtime.schedules import SQLAlchemyAgentScheduleRepository
from margin.agents.context.repository import SQLAlchemyContextRepository
from margin.agents.runtime.service import AgentRuntimeService
from margin.agents.tools.audit import SQLAlchemyToolAuditStore
from margin.agents.workers.dashboard_publisher_worker import DashboardPublisherWorker
from margin.bootstrap.container import AppContainer
from margin.config_runtime.repository import ConfigResolver, SQLAlchemyConfigRepository
from margin.core.orchestration_repository import SQLAlchemyOrchestrationRepository
from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.secret_store import SecretStore
from margin.dashboard.detail_context import make_dashboard_detail_context_loader
from margin.dashboard.repository import SQLAlchemyDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.data.backfill.repository import SQLAlchemyBackfillRepository
from margin.data.backfill.service import BackfillApplicationService
from margin.data.company_pool import SQLAlchemyCompanyPoolRepository
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.policy import (
    DataAcquisitionPolicyService,
    SQLAlchemyDataAcquisitionPolicyRepository,
)
from margin.data.providers.akshare_provider import AKShareProvider
from margin.data.providers.tushare_provider import TushareProvider
from margin.data.warehouse_repository import SQLAlchemyWarehouseRepository
from margin.evidence.package_builder import EvidencePackageBuilder
from margin.evidence.repository import EvidenceRepository
from margin.news.acquirer import HTTPConnector, SnapshotStore, SourceRegistry
from margin.news.agentic_acquisition import AgenticNewsAcquisitionService
from margin.news.article_workflow import ArticleWorkflow
from margin.news.context_bundle import NewsContextBundleBuilder
from margin.news.keyword_workflow import KeywordWorkflow
from margin.news.models import SourceDescriptor, SourceLevel, utc_now
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.quant_targets import SQLAlchemyQuantNewsTargetRepository
from margin.news.refresh_service import NewsRefreshService
from margin.news.repository import NewsRepository
from margin.news.service import NewsService
from margin.news.target_queue import NewsTargetQueue
from margin.news.websearch import WebSearchProvider, WebSearchService
from margin.platform_runtime.repository import (
    MemoryIdempotencyStore,
    SQLAlchemyPlatformRuntimeRepository,
)
from margin.research.delta_repository import SQLAlchemyResearchDeltaRepository
from margin.research.execution.llm_service import LLMService
from margin.research.graph_audit_repository import (
    SQLAlchemyLLMCallAuditRepository,
    SQLAlchemyToolCallAuditRepository,
)
from margin.research.llm import LLMProvider
from margin.research.service import ResearchService
from margin.settings import MarginSettings, get_settings
from margin.strategy.models import ProviderConfigVersion
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
from margin.valuation_discovery.analysis_mart import SQLAlchemyAnalysisMartRepository
from margin.valuation_discovery.assessments import EffectiveAssessmentService
from margin.valuation_discovery.etl import (
    SQLAlchemyQuantFeatureMartETLPipeline,
    build_feature_mart_cross_section_loader,
)
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
from margin.valuation_discovery.service import CompanyProfileService, ValuationDiscoveryService
from margin.vector.indexing_runner import DocumentIndexingRunner
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.providers.rerank import HTTPRerankProvider
from margin.vector.repository import VectorRepository
from margin.vector.retrieval import RetrievalTool


@dataclass(frozen=True)
class MissingConfiguredProvider:
    """Provider-status placeholder for an external provider missing configuration.."""

    descriptor: ProviderDescriptor
    message: str

    def healthcheck(self) -> HealthCheckResult:
        """Return a degraded status without attempting a network call.

        Returns:
            HealthCheckResult: .
        """
        return HealthCheckResult(
            provider_name=self.descriptor.name,
            status=ProviderStatus.DEGRADED,
            checked_at=utc_now(),
            message=self.message,
        )


@dataclass(frozen=True)
class ProviderConfigStatusProbe:
    """Provider-status adapter backed by active encrypted Provider configuration.."""

    config: ProviderConfigVersion
    health_service: ProviderConfigHealthService

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return provider metadata without exposing secrets.

        Returns:
            ProviderDescriptor: .
        """
        provider_type = _provider_type_from_config(self.config.provider_type)
        return ProviderDescriptor(
            name=self.config.provider_name,
            version=self.config.version_id,
            provider_type=provider_type,
            capabilities=_capabilities_for_provider_type(provider_type),
            secret_refs=["provider_database"],
            config={
                "provider_config_version_id": self.config.version_id,
                "source": "provider_database",
            },
        )

    def healthcheck(self) -> HealthCheckResult:
        """Run provider config health through the encrypted Provider database path.

        Returns:
            HealthCheckResult: .
        """
        result = self.health_service.test_connection(self.config.version_id)
        status = {
            "ok": ProviderStatus.HEALTHY,
            "not_configured": ProviderStatus.DEGRADED,
            "failed": ProviderStatus.UNHEALTHY,
        }[result.status]
        return HealthCheckResult(
            provider_name=result.provider_name,
            status=status,
            checked_at=result.checked_at,
            latency_ms=result.latency_ms,
            message=result.redacted_error or result.error_code or result.status,
            details={
                "provider_config_version_id": result.provider_config_version_id,
                "source": "provider_database",
            },
        )


@lru_cache
def get_app_container() -> AppContainer:
    """Return the process-level application container.

    Returns:
        AppContainer: .
    """
    return AppContainer(get_settings())


def build_data_warehouse_stack(
    settings: MarginSettings,
    *,
    default_provider: str = "akshare",
) -> DataWarehouseIngestionStack:
    """Build the data warehouse ingestion stack from centralized settings.

    Args:
        settings: MarginSettings: .
        default_provider: str: .

    Returns:
        DataWarehouseIngestionStack: .
    """
    container = AppContainer(settings)
    return DataWarehouseIngestionStack(
        session_factory=container.session_factory,
        snapshot_root=settings.data_snapshot_root,
        default_provider=default_provider,
    )


def _missing_provider(
    *,
    name: str,
    provider_type: ProviderType,
    message: str,
    capabilities: list[str],
    secret_refs: list[str],
) -> MissingConfiguredProvider:
    """missing provider.

    Args:
        name: str: .
        provider_type: ProviderType: .
        message: str: .
        capabilities: list[str]: .
        secret_refs: list[str]: .

    Returns:
        MissingConfiguredProvider: .
    """
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


def build_provider_status_providers(
    repository: SQLAlchemyStrategyRepository,
    health_service: ProviderConfigHealthService,
    *,
    owner_id: str = "local-admin",
) -> list[Any]:
    """Build all providers surfaced by the dashboard status endpoint.

    Args:
        repository: SQLAlchemyStrategyRepository: .
        health_service: ProviderConfigHealthService: .
        owner_id: str: .

    Returns:
        list[Any]: .
    """
    active_configs = repository.list_active_provider_configs(owner_id)
    probes: list[Any] = [
        ProviderConfigStatusProbe(config=config, health_service=health_service)
        for config in active_configs
    ]
    active_types = {_provider_type_from_config(config.provider_type) for config in active_configs}
    required = (
        ("llm", ProviderType.LLM, "LLM 配置未激活，请到设置页配置模型服务。"),
        (
            "embedding",
            ProviderType.EMBEDDING,
            "向量化模型未激活，请到设置页配置 Embedding 服务。",
        ),
        (
            "websearch",
            ProviderType.WEB_SEARCH,
            "网页搜索未激活，请到设置页配置搜索服务。",
        ),
        ("rerank", ProviderType.RERANK, "Rerank 未激活，可在设置页按需配置。"),
    )
    for name, provider_type, message in required:
        if provider_type not in active_types:
            probes.append(
                _missing_provider(
                    name=name,
                    provider_type=provider_type,
                    capabilities=_capabilities_for_provider_type(provider_type),
                    secret_refs=["provider_database"],
                    message=message,
                )
            )
    return probes


def _provider_type_from_config(value: str) -> ProviderType:
    """Map persisted provider type strings into core provider types.

    Args:
        value: str: .

    Returns:
        ProviderType: .
    """
    normalized = value.strip().lower()
    aliases = {
        "websearch": ProviderType.WEB_SEARCH,
        "web_search": ProviderType.WEB_SEARCH,
        "market_data": ProviderType.MARKET_DATA,
        "llm": ProviderType.LLM,
        "embedding": ProviderType.EMBEDDING,
        "rerank": ProviderType.RERANK,
    }
    return aliases.get(normalized, ProviderType.NOTIFICATION)


def _capabilities_for_provider_type(provider_type: ProviderType) -> list[str]:
    """Return dashboard-safe capability labels for provider status.

    Args:
        provider_type: ProviderType: .

    Returns:
        list[str]: .
    """
    return {
        ProviderType.LLM: ["complete", "complete_structured"],
        ProviderType.EMBEDDING: ["embed", "embed_batch"],
        ProviderType.WEB_SEARCH: ["search"],
        ProviderType.RERANK: ["rerank"],
        ProviderType.MARKET_DATA: ["market_data"],
    }.get(provider_type, [])


@lru_cache
def get_strategy_repository() -> SQLAlchemyStrategyRepository:
    """Return the production PostgreSQL-backed strategy config repository.

    Returns:
        SQLAlchemyStrategyRepository: .
    """
    return get_app_container().strategy_repository


@lru_cache
def get_strategy_service() -> StrategyService:
    """Return the production PostgreSQL-backed strategy configuration service.

    Returns:
        StrategyService: .
    """
    return get_app_container().strategy_service


@lru_cache
def get_secret_store() -> SecretStore:
    """Return the encrypted provider Secret Store.

    Returns:
        SecretStore: .
    """
    return get_app_container().secret_store


def get_optional_secret_store() -> SecretStore | None:
    """Return Secret Store when decrypt authority is configured.

    Returns:
        SecretStore | None: .
    """
    try:
        return get_secret_store()
    except RuntimeError:
        return None


@lru_cache
def get_provider_runtime_factory() -> ProviderRuntimeFactory:
    """Return the strict active-config Provider factory used by business runs.

    Returns:
        ProviderRuntimeFactory: .
    """
    return ProviderRuntimeFactory(
        ProviderRuntimeResolver(
            get_strategy_repository(),
            get_secret_store(),
        )
    )


def get_llm_provider_factory(
    runtime_factory: Annotated[
        ProviderRuntimeFactory,
        Depends(get_provider_runtime_factory),
    ],
) -> Callable[[], LLMProvider]:
    """Return a lazy factory for the active LLM provider.

    Args:
        runtime_factory: Annotated[ProviderRuntimeFactory, Depends(get_provider_runtime_factory)]: .

    Returns:
        Callable[[], LLMProvider]: .
    """
    return lambda: runtime_factory.build_llm().adapter


@lru_cache
def get_config_repository() -> SQLAlchemyConfigRepository:
    """Return the domain-specific runtime config repository.

    Returns:
        SQLAlchemyConfigRepository: .
    """
    return SQLAlchemyConfigRepository(get_app_container().session_factory)


@lru_cache
def get_config_resolver() -> ConfigResolver:
    """Return the unified runtime config resolver.

    Returns:
        ConfigResolver: .
    """
    return ConfigResolver(
        get_config_repository(),
        environment=get_settings().environment,
    )


@lru_cache
def get_agent_context_store() -> SQLAlchemyAgentContextStore:
    """Return the persisted Agent context store.

    Returns:
        SQLAlchemyAgentContextStore: .
    """
    return SQLAlchemyAgentContextStore(get_app_container().session_factory)


@lru_cache
def get_context_repository() -> SQLAlchemyContextRepository:
    """Return the structured Context Engineering repository.

    Returns:
        SQLAlchemyContextRepository: .
    """
    return SQLAlchemyContextRepository(get_app_container().session_factory)


@lru_cache
def get_idempotency_store() -> SQLAlchemyPlatformRuntimeRepository | MemoryIdempotencyStore:
    """Return the platform idempotency store used by mutating agent routes.

    Returns:
        SQL-backed store in production processes; tests override via create_app.
    """
    return SQLAlchemyPlatformRuntimeRepository(get_app_container().session_factory)


@lru_cache
def get_agent_runtime_service() -> AgentRuntimeService:
    """Return the v1 application-facing Agent runtime service.

    Returns:
        AgentRuntimeService: .
    """
    runtime_factory = get_provider_runtime_factory()
    container = get_app_container()
    return AgentRuntimeService(
        context_store=get_agent_context_store(),
        context_repository=get_context_repository(),
        dashboard_services=get_dashboard_services(),
        llm_provider_factory=lambda: runtime_factory.build_llm().adapter,
        warehouse_repository=SQLAlchemyWarehouseRepository(container.session_factory),
        tool_audit_store=get_tool_audit_store(),
    )


@lru_cache
def get_agent_schedule_repository() -> SQLAlchemyAgentScheduleRepository:
    """Return the persisted agent schedule repository.

    Returns:
        SQLAlchemyAgentScheduleRepository: .
    """
    return SQLAlchemyAgentScheduleRepository(get_app_container().session_factory)


@lru_cache
def get_agent_chat_repository() -> SQLAlchemyAgentChatRepository:
    """Return the persisted Agent chat repository.

    Returns:
        SQLAlchemyAgentChatRepository: .
    """
    return SQLAlchemyAgentChatRepository(get_app_container().session_factory)


def get_provider_config_health_service(
    repository: Annotated[
        SQLAlchemyStrategyRepository,
        Depends(get_strategy_repository),
    ],
    secret_store: Annotated[SecretStore, Depends(get_secret_store)],
) -> ProviderConfigHealthService:
    """Return provider health service using frozen configs and encrypted secrets.

    Args:
        repository: Annotated[SQLAlchemyStrategyRepository, Depends(get_strategy_repository)]: .
        secret_store: Annotated[SecretStore, Depends(get_secret_store)]: .

    Returns:
        ProviderConfigHealthService: .
    """
    settings = get_settings()
    return ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters=_build_provider_health_adapters(),
        host_allowlists={
            "tushare": {"api.tushare.pro", "teajoin.com"},
            "tavily": {"api.tavily.com"},
            "tavily_websearch": {"api.tavily.com"},
            "llm": {
                "api.openai.com",
                "api.deepseek.com",
                "api.minimaxi.com",
                "platform.minimaxi.com",
            },
            "openai_llm": {
                "api.openai.com",
                "api.deepseek.com",
                "api.minimaxi.com",
                "platform.minimaxi.com",
            },
            "embedding": {"api.openai.com", "open.bigmodel.cn"},
            "openai_embedding": {"api.openai.com", "open.bigmodel.cn"},
            "rerank": {"api.cohere.com"},
            "http_rerank": {"api.cohere.com"},
        },
        allow_local_development=settings.allow_local_provider_urls,
        resolve_dns=settings.resolve_provider_dns,
    )


def _build_provider_health_adapters() -> dict[str, HealthCheckCallable]:
    """Build real read-only provider health adapters keyed by config name.

    Returns:
        dict[str, HealthCheckCallable]: .
    """

    def tushare_health(config, secret: str) -> None:
        """Run a read-only Tushare health check and raise on degraded status.

        Args:
            config: Any: .
            secret: str: .

        Returns:
            None: .
        """
        endpoint = config.base_url or config.non_sensitive_config.get("http_url")
        _require_healthy(TushareProvider(token=secret, http_url=endpoint).healthcheck())

    def akshare_health(_config, _secret: str) -> None:
        """Run a read-only AKShare health check and raise on degraded status.

        Args:
            _config: Any: .
            _secret: str: .

        Returns:
            None: .
        """
        _require_healthy(AKShareProvider().healthcheck())

    def tavily_health(config, secret: str) -> None:
        """Run a read-only Tavily health check and raise on degraded status.

        Args:
            config: Any: .
            secret: str: .

        Returns:
            None: .
        """
        kwargs: dict[str, Any] = {"api_key": secret}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        _require_healthy(TavilySearchAdapter(**kwargs).healthcheck())

    def llm_health(config, secret: str) -> None:
        """Run a read-only LLM health check and raise on degraded status.

        Args:
            config: Any: .
            secret: str: .

        Returns:
            None: .
        """
        _require_healthy(
            LLMProvider(
                api_key=secret,
                base_url=config.base_url,
                model=config.model_name,
            ).healthcheck()
        )

    def embedding_health(config, secret: str) -> None:
        """Run a read-only embedding health check and raise on degraded status.

        Args:
            config: Any: .
            secret: str: .

        Returns:
            None: .
        """
        dimension = int(config.non_sensitive_config.get("dimension", 1536))
        _require_healthy(
            OpenAIEmbeddingProvider(
                api_key=secret,
                base_url=config.base_url,
                model=config.model_name,
                dimension=dimension,
            ).healthcheck()
        )

    def rerank_health(config, secret: str) -> None:
        """Run a read-only rerank health check and raise on degraded status.

        Args:
            config: Any: .
            secret: str: .

        Returns:
            None: .
        """
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
    """require healthy.

    Args:
        result: HealthCheckResult: .

    Returns:
        None: .
    """
    if result.status is not ProviderStatus.HEALTHY:
        raise RuntimeError(result.message or f"provider health status: {result.status.value}")


def require_local_admin(
    authorization: Annotated[
        str | None,
        Header(alias="Authorization"),
    ] = None,
) -> str:
    """Resolve the local personal-mode actor for mutating API calls.

    Args:
        authorization: Annotated[str | None, Header(alias='Authorization')]: .

    Returns:
        str: .
    """
    settings = get_settings()
    if settings.environment == "production":
        expected = (
            settings.admin_api_token.get_secret_value()
            if settings.admin_api_token is not None
            else ""
        )
        if authorization != f"Bearer {expected}":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="admin bearer token is required",
            )
    return "local-admin"


def require_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> str:
    """Require a non-empty idempotency key for a mutating request.

    Args:
        idempotency_key: Annotated[str | None, Header(alias='Idempotency-Key')]: .

    Returns:
        str: .
    """
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    return idempotency_key.strip()


@lru_cache
def get_valuation_discovery_service() -> ValuationDiscoveryService:
    """Return the production valuation discovery service.

    Returns:
        ValuationDiscoveryService: .
    """
    settings = get_settings()
    container = get_app_container()
    session_factory = container.session_factory

    orchestration_repository = ValuationDiscoveryOrchestrationRepository(
        SQLAlchemyOrchestrationRepository(session_factory)
    )

    strategy_repository = container.strategy_repository
    company_pool_repository = SQLAlchemyCompanyPoolRepository(session_factory)
    scope_provider = SQLAlchemyScopeBindingProvider(
        strategy_repository,
        company_pool_repository=company_pool_repository,
    )
    warehouse_repository = SQLAlchemyWarehouseRepository(session_factory)
    warehouse_fact_adapter = WarehouseFactAdapter(warehouse_repository)
    valuation_repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
    analysis_mart_repository = SQLAlchemyAnalysisMartRepository(session_factory)
    snapshot_builder = QuantInputSnapshotBuilder(
        repository=valuation_repository,
        warehouse_repository=warehouse_fact_adapter,
    )
    feature_mart_etl = SQLAlchemyQuantFeatureMartETLPipeline(
        session_factory,
        source_loader=build_cross_section_loader(warehouse_repository),
    )
    quant_repository = SQLAlchemyQuantRepository(
        session_factory,
        cross_section_loader=build_feature_mart_cross_section_loader(analysis_mart_repository),
    )
    quant_service = QuantService(repository=quant_repository)
    quant_adapter = QuantAdapter(
        quant_service=quant_service,
        snapshot_builder=snapshot_builder,
        scope_provider=scope_provider,
        quant_repository=quant_repository,
        feature_mart_pipeline=feature_mart_etl,
    )

    news_target_selector = NewsTargetSelector()

    runtime_factory = get_provider_runtime_factory()
    market_runtime = runtime_factory.build_market_data("quant_required_financials")
    ingestion_stack = DataWarehouseIngestionStack(
        session_factory=session_factory,
        snapshot_root=settings.data_snapshot_root,
        default_provider=market_runtime.adapter.descriptor.name,
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
        news_bundle_builder=NewsContextBundleBuilder(NewsRepository(session_factory)),
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
        analysis_mart_repository=analysis_mart_repository,
    )
    ai_review_service = AIReviewAdapter(
        research_service,
        session_factory=session_factory,
    )

    assessment_service = EffectiveAssessmentService()
    dashboard_repository = SQLAlchemyDashboardRepository(session_factory)
    valuation_publisher = ValuationPublisherAdapter(
        assessment_service=assessment_service,
        review_repository=SQLAlchemyResearchDeltaRepository(session_factory),
        valuation_repository=valuation_repository,
        dashboard_repository=dashboard_repository,
        stock_analyst_agent=DashboardPublisherWorker(
            write_context_artifact=get_agent_context_store().add_artifact,
            dashboard_repository=dashboard_repository,
        ),
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
    """Return valuation discovery service or a typed API configuration error.

    Returns:
        ValuationDiscoveryService: .
    """
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
    """Return true for expected runtime provider configuration gaps.

    Args:
        message: str: .

    Returns:
        bool: .
    """
    return any(
        marker in message
        for marker in (
            "active provider config not found",
            "active provider secret not configured",
            "active provider references inactive secret",
            "provider secret not configured",
            "provider secret reference mismatch",
        )
    )


@lru_cache
def get_valuation_discovery_step_worker() -> ValuationDiscoveryStepWorker:
    """Return the background worker for durable valuation-discovery steps.

    Returns:
        ValuationDiscoveryStepWorker: .
    """
    service = get_valuation_discovery_service()
    return service.create_step_worker(
        worker_id=f"{get_settings().service_name}-valuation-discovery",
    )


@lru_cache
def get_company_profile_service() -> CompanyProfileService:
    """Return a cached company profile service for quant/analysis visualization.

    Returns:
        CompanyProfileService: .
    """
    session_factory = get_app_container().session_factory
    quant_repository = SQLAlchemyQuantRepository(
        session_factory,
        cross_section_loader=build_feature_mart_cross_section_loader(
            SQLAlchemyAnalysisMartRepository(session_factory)
        ),
    )
    analysis_mart_repository = SQLAlchemyAnalysisMartRepository(session_factory)
    return CompanyProfileService(
        quant_repository=quant_repository,
        analysis_mart_repository=analysis_mart_repository,
    )


def _build_news_refresh_adapter(
    settings: MarginSettings,
    session_factory: Any,
    *,
    runtime_factory: ProviderRuntimeFactory,
) -> NewsRefreshAdapter:
    """Build news refresh from the active frozen WebSearch configuration.

    Args:
        settings: MarginSettings: .
        session_factory: Any: .
        runtime_factory: ProviderRuntimeFactory: .

    Returns:
        NewsRefreshAdapter: .
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
        snapshot_store=SnapshotStore(base_dir=settings.data_snapshot_root.parent / "news"),
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
        settings: MarginSettings: .
        session_factory: Any: .
        runtime_factory: ProviderRuntimeFactory: .

    Returns:
        DocumentIndexingRunner: .
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
        session_factory: Any: .
        runtime_factory: ProviderRuntimeFactory: .

    Returns:
        ResearchService: .
    """
    llm_provider = runtime_factory.build_llm().adapter
    embedding_provider = runtime_factory.build_embedding().adapter
    vector_repository = VectorRepository(
        session_factory,
        dimension=embedding_provider.dim,
    )
    evidence_repository = EvidenceRepository(session_factory)
    return ResearchService(
        llm_provider=llm_provider,
        session_factory=session_factory,
        v02_llm_audit_repository=SQLAlchemyLLMCallAuditRepository(session_factory),
        v02_tool_audit_repository=SQLAlchemyToolCallAuditRepository(session_factory),
        rag_retrieval_tool=RetrievalTool(
            PersistentEmbeddingPipeline(
                embedding_provider=embedding_provider,
                repository=vector_repository,
            )
        ),
        rag_evidence_package_builder=EvidencePackageBuilder(
            vector_repository,
            evidence_repository,
        ),
    )


@lru_cache
def get_news_service() -> NewsService:
    """Return production target-driven news refresh service.

    Returns:
        NewsService: .
    """
    settings = get_settings()
    try:
        tavily_adapter = get_provider_runtime_factory().build_websearch().adapter
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="active websearch provider is not available",
        ) from exc
    session_factory = get_app_container().session_factory
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
def get_agentic_news_service() -> AgenticNewsAcquisitionService:
    """Return production agentic news acquisition service.

    Returns:
        AgenticNewsAcquisitionService: .
    """
    settings = get_settings()
    try:
        llm_provider, tavily_adapter = _build_agentic_news_providers(settings)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="active LLM or websearch provider is not available",
        ) from exc
    session_factory = get_app_container().session_factory
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
    llm_service = _build_agentic_news_llm_service(llm_provider)
    return AgenticNewsAcquisitionService(
        repository=repository,
        target_repository=SQLAlchemyQuantNewsTargetRepository(session_factory),
        keyword_workflow=KeywordWorkflow(llm_service=llm_service),
        websearch_service=websearch_service,
        article_workflow=ArticleWorkflow(llm_service=llm_service),
    )


def _build_agentic_news_providers(_settings: MarginSettings) -> tuple[Any, Any]:
    """Build LLM and WebSearch providers for agentic news.

    Args:
        _settings: MarginSettings: .

    Returns:
        tuple[Any, Any]: .
    """
    try:
        runtime_factory = get_provider_runtime_factory()
        return (
            runtime_factory.build_llm().adapter,
            runtime_factory.build_websearch().adapter,
        )
    except (LookupError, RuntimeError, ValueError) as exc:
        raise RuntimeError("active LLM or websearch provider is not available") from exc


def _build_agentic_news_llm_service(llm_provider: Any) -> LLMService:
    """Build the LLM service for agentic news.

    Args:
        llm_provider: Any: .

    Returns:
        LLMService: .
    """
    return LLMService(llm_provider)


@lru_cache
def get_data_warehouse_stack() -> DataWarehouseIngestionStack:
    """Return the production data warehouse ingestion stack.

    Returns:
        DataWarehouseIngestionStack: .
    """
    return build_data_warehouse_stack(
        get_settings(),
        default_provider=_default_market_data_provider(),
    )


def _default_market_data_provider() -> str:
    """Resolve the default data-sync provider by runtime capability.

    Returns:
        str: .
    """
    runtime_factory = get_provider_runtime_factory()
    try:
        return runtime_factory.build_market_data(
            "quant_required_financials"
        ).adapter.descriptor.name
    except (LookupError, RuntimeError, ValueError):
        try:
            return runtime_factory.build_market_data("market_quote").adapter.descriptor.name
        except (LookupError, RuntimeError, ValueError):
            return "akshare"


@lru_cache
def get_data_policy_service() -> DataAcquisitionPolicyService:
    """Return the PostgreSQL-backed rolling-window policy service.

    Returns:
        DataAcquisitionPolicyService: .
    """
    container = get_app_container()
    repository = SQLAlchemyDataAcquisitionPolicyRepository(container.session_factory)
    return DataAcquisitionPolicyService(repository)


@lru_cache
def get_backfill_application_service() -> BackfillApplicationService:
    """Return the PostgreSQL-backed backfill control-plane service.

    Returns:
        BackfillApplicationService: .
    """
    return BackfillApplicationService(
        repository=SQLAlchemyBackfillRepository(get_app_container().session_factory)
    )


@lru_cache
def get_tool_audit_store() -> SQLAlchemyToolAuditStore:
    """Return the persisted safe tool audit store.

    Returns:
        SQLAlchemyToolAuditStore: .
    """
    return SQLAlchemyToolAuditStore(get_app_container().session_factory)


@lru_cache
def get_dashboard_services() -> DashboardServiceBundle:
    """Return production dashboard services backed by PostgreSQL.

    Returns:
        DashboardServiceBundle: .
    """
    container = get_app_container()
    session_factory = container.session_factory
    dashboard_repository = SQLAlchemyDashboardRepository(session_factory)
    strategy_repository = container.strategy_repository
    secret_store = container.secret_store
    health_service = get_provider_config_health_service(
        strategy_repository,
        secret_store,
    )
    quant_profile_loader = _build_dashboard_quant_profile_loader()
    detail_context_loader = make_dashboard_detail_context_loader(
        session_factory=session_factory,
        warehouse_repository=SQLAlchemyWarehouseRepository(session_factory),
    )
    return DashboardServiceBundle.from_repositories(
        dashboard_repository=dashboard_repository,
        providers=build_provider_status_providers(
            strategy_repository,
            health_service,
        ),
        quant_profile_loader=quant_profile_loader,
        detail_context_loader=detail_context_loader,
    )


def _build_dashboard_quant_profile_loader() -> Callable[[str], dict[str, Any] | None]:
    """Return a callable that loads a quant profile dict for a security id.

    Returns:
        Callable[[str], dict[str, Any] | None]: .
    """
    profile_service = get_company_profile_service()

    def loader(security_id: str) -> dict[str, Any] | None:
        """Process loader.

        Args:
            security_id: str: .

        Returns:
            dict[str, Any] | None: .
        """
        profile = profile_service.get_quant_profile(security_id)
        if profile is None:
            return None
        return {
            "display_name": profile.factor_details.get("name"),
            "final_score": profile.final_score,
            "factor_scores": [
                {
                    "factor_key": item.factor_key,
                    "label": item.label,
                    "score": item.score,
                    "weight": item.weight,
                }
                for item in profile.factor_scores
            ],
            "rank_overall": profile.rank_overall,
            "rank_in_industry": profile.rank_in_industry,
            "screening_status": profile.screening_status,
            "research_guardrail": profile.research_guardrail,
            "reason_summary": profile.reason_summary,
            "factor_details": profile.factor_details,
        }

    return loader


def clear_provider_runtime_caches() -> None:
    """Clear cached services that bind active Provider runtime adapters.

    Returns:
        None: .
    """
    get_app_container.cache_clear()
    get_provider_runtime_factory.cache_clear()
    get_news_service.cache_clear()
    get_agentic_news_service.cache_clear()
    get_valuation_discovery_service.cache_clear()
    get_valuation_discovery_step_worker.cache_clear()
    get_backfill_application_service.cache_clear()
    get_tool_audit_store.cache_clear()
    get_dashboard_services.cache_clear()
    # Agent runtime freezes the planning LLM adapter at construction time.
    get_agent_runtime_service.cache_clear()
    get_agent_context_store.cache_clear()
    get_context_repository.cache_clear()
