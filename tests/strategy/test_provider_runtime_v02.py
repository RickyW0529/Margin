"""Runtime resolution tests for active versioned Provider configuration.

This module validates that the provider runtime resolver and factory return
only active configurations with frozen secrets, reject draft configs, and
support secretless providers.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from margin.core.secret_store import (
    SecretStore,
    SQLAlchemySecretRepository,
    WriteSecretCommand,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.models import ConfigLifecycle, ProviderConfigVersion
from margin.strategy.provider_config import ProviderConfigHealthService
from margin.strategy.provider_runtime import (
    ProviderRuntimeFactory,
    ProviderRuntimeResolver,
)
from margin.strategy.repository import MemoryStrategyRepository
from margin.strategy.service import StrategyService


@pytest.fixture
def secret_store(database_url: str) -> SecretStore:
    """Return an isolated encrypted Secret Store.

    Args:
        database_url: str: .

    Returns:
        SecretStore: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    repository = SQLAlchemySecretRepository(create_session_factory(engine))
    return SecretStore(repository, master_key=os.urandom(32))


def test_runtime_resolves_only_active_config_and_frozen_secret(
    secret_store: SecretStore,
) -> None:
    """Verify runtime consumers receive the active config and its exact secret version.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="llm",
            secret_name="api_key",
            secret_value="runtime-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-secret-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-active",
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-pro",
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    resolved = ProviderRuntimeResolver(repository, secret_store).resolve("llm")

    assert resolved.config.version_id == "provider-llm-active"
    assert resolved.secret is not None
    assert resolved.secret.get_secret_value() == "runtime-secret"
    assert "runtime-secret" not in repr(resolved)


def test_runtime_rejects_missing_active_provider(
    secret_store: SecretStore,
) -> None:
    """Verify a draft configuration is not executable at runtime.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-draft",
            provider_name="llm",
            provider_type="llm",
            lifecycle=ConfigLifecycle.DRAFT,
        )
    )

    with pytest.raises(LookupError, match="active provider config not found"):
        ProviderRuntimeResolver(repository, secret_store).resolve("llm")


def test_runtime_supports_explicit_secretless_provider(
    secret_store: SecretStore,
) -> None:
    """Verify providers such as AKShare may be explicitly configured as secretless.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-akshare-active",
            provider_name="akshare",
            provider_type="market_data",
            non_sensitive_config={"secret_required": False},
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    resolved = ProviderRuntimeResolver(repository, secret_store).resolve("akshare")

    assert resolved.config.version_id == "provider-akshare-active"
    assert resolved.secret is None


def test_runtime_resolves_data_source_by_capability(
    secret_store: SecretStore,
) -> None:
    """Verify runtime consumers can request a capability instead of a provider name.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="tushare",
            secret_name="api_key",
            secret_value="tushare-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-capability-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-akshare-active",
            provider_name="akshare",
            provider_type="market_data",
            non_sensitive_config={"secret_required": False},
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-tushare-active",
            provider_name="tushare",
            provider_type="market_data",
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    resolved = ProviderRuntimeResolver(
        repository,
        secret_store,
    ).resolve_capability("data_source", "quant_required_financials")

    assert resolved.config.provider_name == "tushare"
    assert resolved.config.version_id == "provider-tushare-active"


def test_runtime_resolves_detected_tushare_proxy_from_legacy_generic_name(
    secret_store: SecretStore,
) -> None:
    """Legacy generic data-source configs should use detected Tushare capabilities."""
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="provider-data-source-legacy",
            secret_name="api_token",
            secret_value="tushare-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-tushare-proxy-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-data-source-legacy",
            provider_name="data_source",
            provider_type="market_data",
            base_url="https://teajoin.com",
            non_sensitive_config={
                "provider_category": "data_source",
                "detected_provider": "tushare",
            },
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    resolved = ProviderRuntimeResolver(
        repository,
        secret_store,
    ).resolve_capability("data_source", "quant_required_financials")

    assert resolved.config.version_id == "provider-data-source-legacy"
    assert resolved.config.provider_name == "data_source"


def test_runtime_rejects_ambiguous_provider_capability(
    secret_store: SecretStore,
) -> None:
    """Verify explicit capabilities cannot silently select among duplicates.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    for provider_name in ("first-source", "second-source"):
        repository.save_provider_config(
            ProviderConfigVersion(
                version_id=f"provider-{provider_name}",
                provider_name=provider_name,
                provider_type="market_data",
                non_sensitive_config={
                    "secret_required": False,
                    "capabilities": ["custom_quote"],
                },
                lifecycle=ConfigLifecycle.ACTIVE,
            )
        )

    with pytest.raises(RuntimeError, match="multiple active provider configs"):
        ProviderRuntimeResolver(
            repository,
            secret_store,
        ).resolve_capability("data_source", "custom_quote")


def test_runtime_factory_builds_market_data_by_capability(
    secret_store: SecretStore,
) -> None:
    """Verify market data adapters can be built by capability.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-akshare-capability",
            provider_name="akshare",
            provider_type="market_data",
            non_sensitive_config={"secret_required": False},
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    runtime = ProviderRuntimeFactory(
        ProviderRuntimeResolver(repository, secret_store)
    ).build_market_data("market_quote")

    assert runtime.config_version_id == "provider-akshare-capability"
    assert runtime.adapter.descriptor.name == "akshare"


def test_runtime_factory_builds_adapter_with_config_version_lineage(
    secret_store: SecretStore,
) -> None:
    """Verify factory output preserves the exact active config version used.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="llm",
            secret_name="api_key",
            secret_value="runtime-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-factory-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-runtime-v1",
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-pro",
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    runtime = ProviderRuntimeFactory(ProviderRuntimeResolver(repository, secret_store)).build_llm()

    assert runtime.config_version_id == "provider-llm-runtime-v1"
    assert runtime.adapter.descriptor.config["base_url"] == "https://api.deepseek.com"
    assert runtime.adapter.descriptor.config["model"] == "deepseek-v4-pro"
    assert "runtime-secret" not in repr(runtime)


def test_runtime_factory_builds_llm_from_active_provider_category(
    secret_store: SecretStore,
) -> None:
    """LLM runtime should resolve active DeepSeek configs by category.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="deepseek",
            secret_name="api_key",
            secret_value="deepseek-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-deepseek-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-deepseek-active",
            provider_name="deepseek",
            provider_type="llm",
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat",
            non_sensitive_config={"provider_category": "llm"},
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    runtime = ProviderRuntimeFactory(ProviderRuntimeResolver(repository, secret_store)).build_llm()

    assert runtime.config_version_id == "provider-deepseek-active"
    assert runtime.adapter.descriptor.config["base_url"] == "https://api.deepseek.com/v1"
    assert runtime.adapter.descriptor.config["model"] == "deepseek-chat"


def test_runtime_factory_uses_secret_written_by_provider_settings_flow(
    secret_store: SecretStore,
) -> None:
    """Runtime factory must use encrypted secrets written by Provider Settings.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    repository = MemoryStrategyRepository()
    service = StrategyService(repository)
    version_id = "provider-llm-settings-flow"
    suffix = uuid4().hex
    service.create_provider_config(
        ProviderConfigVersion(
            version_id=version_id,
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat",
            non_sensitive_config={"provider_category": "llm"},
        ),
        actor_id="local-admin",
        idempotency_key=f"create-{version_id}-{suffix}",
    )
    service.write_provider_secret(
        provider_config_version_id=version_id,
        secret_name="api_key",
        secret_value="deepseek-settings-secret",
        actor_id="local-admin",
        idempotency_key=f"secret-{version_id}-{suffix}",
        secret_store=secret_store,
    )
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={"llm": lambda _config, _secret: None},
    )
    service.activate_provider_config(
        version_id,
        health_service=health_service,
        actor_id="local-admin",
        idempotency_key=f"activate-{version_id}-{suffix}",
    )

    runtime = ProviderRuntimeFactory(ProviderRuntimeResolver(repository, secret_store)).build_llm()

    assert runtime.config_version_id == version_id
    assert runtime.adapter.descriptor.config["base_url"] == "https://api.deepseek.com/v1"
    assert runtime.adapter.descriptor.config["model"] == "deepseek-chat"


def test_runtime_factory_builds_embedding_from_active_provider_category(
    secret_store: SecretStore,
) -> None:
    """Embedding runtime should resolve active provider configs by category.

    Args:
        secret_store: SecretStore: .

    Returns:
        None: .
    """
    metadata = secret_store.create_or_replace(
        WriteSecretCommand(
            provider_name="jina",
            secret_name="api_key",
            secret_value="jina-secret",
            actor_id="local-admin",
            idempotency_key=f"runtime-jina-{uuid4().hex}",
        )
    )
    repository = MemoryStrategyRepository()
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-jina-embedding-active",
            provider_name="jina",
            provider_type="embedding",
            base_url="https://api.jina.ai/v1/embeddings",
            model_name="jina-embeddings-v3",
            non_sensitive_config={"provider_category": "embedding", "dimension": 1024},
            secret_version_id=metadata.version_id,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    )

    runtime = ProviderRuntimeFactory(
        ProviderRuntimeResolver(repository, secret_store)
    ).build_embedding()

    assert runtime.config_version_id == "provider-jina-embedding-active"
    assert runtime.adapter.descriptor.config["base_url"] == ("https://api.jina.ai/v1/embeddings")
    assert runtime.adapter.descriptor.config["model"] == "jina-embeddings-v3"
