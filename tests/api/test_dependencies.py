"""Tests for production dependency construction from MarginSettings."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import margin.api.dependencies as dependencies
from margin.api.dependencies import (
    build_data_warehouse_stack,
    build_provider_status_providers,
    get_provider_config_health_service,
    get_provider_runtime_factory,
)
from margin.core.secret_store import (
    SecretStore,
    SQLAlchemySecretRepository,
    WriteSecretCommand,
)
from margin.settings import MarginSettings
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.models import ConfigLifecycle, ProviderConfigVersion
from margin.strategy.provider_config import ProviderHealth
from margin.strategy.repository import MemoryStrategyRepository


def test_provider_status_providers_use_active_provider_configs() -> None:
    """Test that provider status reads active provider DB configs, not env.

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-active-v1",
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-pro",
            secret_version_id="secret-llm-v1",
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    class FakeHealthService:
        """Minimal provider health service for status-probe tests.."""

        def test_connection(self, version_id: str) -> ProviderHealth:
            """Return a healthy DB-backed provider health result.

            Args:
                version_id: str: .

            Returns:
                ProviderHealth: .
            """
            return ProviderHealth(
                provider_name="llm",
                provider_config_version_id=version_id,
                status="ok",
                checked_at=datetime(2026, 7, 1, tzinfo=UTC),
            )

    providers = build_provider_status_providers(repository, FakeHealthService())
    names = [provider.descriptor.name for provider in providers]
    statuses = {provider.descriptor.name: provider.healthcheck() for provider in providers}

    assert "llm" in names
    assert "embedding" in names
    assert "websearch" in names
    assert "rerank" in names
    assert statuses["llm"].status.value == "healthy"
    assert statuses["embedding"].status.value == "degraded"
    assert "provider_database" in providers[0].descriptor.secret_refs
    assert all("MARGIN_" not in ",".join(provider.descriptor.secret_refs) for provider in providers)


def test_build_data_warehouse_stack_uses_centralized_settings(database_url, tmp_path):
    """Test that build_data_warehouse_stack uses centralized settings.

    Args:
        database_url: Any: .
        tmp_path: Any: .

    Returns:
        Any: .
    """
    settings = MarginSettings(
        _env_file=None,
        database_url=database_url,
        data_snapshot_root=tmp_path,
    )

    stack = build_data_warehouse_stack(settings)

    assert stack.warehouse is not None


def test_runtime_factory_dependency_uses_active_versioned_config(
    database_url: str,
    monkeypatch,
) -> None:
    """Test that production runtime construction reads versioned config, not env.

    Args:
        database_url: str: .
        monkeypatch: Any: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="llm",
            secret_name="api_key",
            secret_value="versioned-secret",
            actor_id="local-admin",
            idempotency_key=f"dependency-runtime-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-dependency-v1",
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-pro",
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    monkeypatch.setattr(
        dependencies,
        "get_strategy_repository",
        lambda: repository,
    )
    monkeypatch.setattr(dependencies, "get_secret_store", lambda: secret_store)
    get_provider_runtime_factory.cache_clear()

    runtime = get_provider_runtime_factory().build_llm()

    assert runtime.config_version_id == "provider-llm-dependency-v1"
    engine.dispose()


def test_optional_firecrawl_adapter_uses_active_runtime_descriptor() -> None:
    """Agent dependency wiring should expose only a Firecrawl websearch adapter."""
    firecrawl = SimpleNamespace(
        descriptor=SimpleNamespace(name="firecrawl_websearch")
    )
    factory = SimpleNamespace(
        build_websearch=lambda: SimpleNamespace(adapter=firecrawl)
    )

    assert dependencies._optional_firecrawl_adapter(factory) is firecrawl

    tavily = SimpleNamespace(descriptor=SimpleNamespace(name="tavily_websearch"))
    non_firecrawl_factory = SimpleNamespace(
        build_websearch=lambda: SimpleNamespace(adapter=tavily)
    )
    assert dependencies._optional_firecrawl_adapter(non_firecrawl_factory) is None


def test_provider_health_dependency_allows_minimax_llm_host() -> None:
    """Production LLM host allowlist should include Minimax API hosts."""
    service = get_provider_config_health_service(
        MemoryStrategyRepository(),
        object(),  # type: ignore[arg-type]
    )

    service.validate_base_url(
        "https://platform.minimaxi.com",
        provider_name="llm",
    )
    service.validate_base_url(
        "https://api.minimaxi.com/v1",
        provider_name="llm",
    )


def test_provider_health_dependency_allows_teajoin_tushare_proxy_host() -> None:
    """Production data-source allowlist should include the Tushare proxy host."""
    service = get_provider_config_health_service(
        MemoryStrategyRepository(),
        object(),  # type: ignore[arg-type]
    )

    service.validate_base_url(
        "https://teajoin.com",
        provider_name="tushare",
    )


def test_get_agent_runtime_service_returns_cached_runtime() -> None:
    """Test that the v1 Agent runtime service dependency is cached.

    Returns:
        None: .
    """
    from margin.agent_runtime.context_store import SQLAlchemyAgentContextStore
    from margin.agents.runtime.service import AgentRuntimeService
    from margin.api.dependencies import get_agent_context_store, get_agent_runtime_service

    get_agent_context_store.cache_clear()
    get_agent_runtime_service.cache_clear()
    first = get_agent_runtime_service()
    second = get_agent_runtime_service()

    assert first is second
    assert isinstance(first, AgentRuntimeService)
    assert isinstance(get_agent_context_store(), SQLAlchemyAgentContextStore)
