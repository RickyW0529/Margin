"""Tests for production dependency construction from MarginSettings."""

from __future__ import annotations

import os
from uuid import uuid4

import margin.api.dependencies as dependencies
from margin.api.dependencies import (
    build_data_warehouse_stack,
    build_embedding_provider,
    build_llm_provider,
    build_provider_status_providers,
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
from margin.strategy.repository import MemoryStrategyRepository


def test_build_llm_provider_uses_centralized_settings():
    """Test that build_llm_provider uses centralized settings."""
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )

    provider = build_llm_provider(settings)

    assert provider is not None
    assert provider.descriptor.version == "deepseek-v4-flash"
    assert provider.descriptor.config["base_url"] == "https://api.deepseek.com"


def test_build_embedding_provider_uses_centralized_settings():
    """Test that build_embedding_provider uses centralized settings."""
    settings = MarginSettings(
        _env_file=None,
        embedding_api_key="test-key",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
        embedding_model="embedding-3",
        embedding_dimension=2048,
    )

    provider = build_embedding_provider(settings)

    assert provider is not None
    assert provider.version == "embedding-3"
    assert provider.dim == 2048


def test_provider_factories_fail_closed_when_unconfigured():
    """Test that provider factories fail closed when unconfigured."""
    settings = MarginSettings(_env_file=None)

    assert build_llm_provider(settings) is None
    assert build_embedding_provider(settings) is None


def test_provider_factories_fail_closed_for_empty_container_secrets():
    """Test that provider factories fail closed for empty container secrets."""
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="",
        llm_base_url="https://api.deepseek.com",
        embedding_api_key="",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    assert build_llm_provider(settings) is None
    assert build_embedding_provider(settings) is None


def test_provider_status_providers_report_missing_optional_external_providers():
    """Test that provider status reports missing optional external providers."""
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        embedding_api_key="embedding-key",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    providers = build_provider_status_providers(settings)
    names = [provider.descriptor.name for provider in providers]
    statuses = {provider.descriptor.name: provider.healthcheck() for provider in providers}

    assert "openai_llm" in names
    assert "openai_embedding" in names
    assert "tavily_websearch" in names
    assert "http_rerank" in names
    assert statuses["tavily_websearch"].status.value == "degraded"
    assert statuses["http_rerank"].status.value == "degraded"


def test_build_data_warehouse_stack_uses_centralized_settings(database_url, tmp_path):
    """Test that build_data_warehouse_stack uses centralized settings."""
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
    """Test that production runtime construction reads versioned config, not env."""
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
