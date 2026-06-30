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
from margin.strategy.provider_runtime import (
    ProviderRuntimeFactory,
    ProviderRuntimeResolver,
)
from margin.strategy.repository import MemoryStrategyRepository


@pytest.fixture
def secret_store(database_url: str) -> SecretStore:
    """Return an isolated encrypted Secret Store.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        A SecretStore backed by a fresh in-memory schema with a random master key.
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
        secret_store: Isolated encrypted SecretStore fixture.

    Returns:
        None.
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
        secret_store: Isolated encrypted SecretStore fixture.

    Returns:
        None.
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
        secret_store: Isolated encrypted SecretStore fixture.

    Returns:
        None.
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


def test_runtime_factory_builds_adapter_with_config_version_lineage(
    secret_store: SecretStore,
) -> None:
    """Verify factory output preserves the exact active config version used.

    Args:
        secret_store: Isolated encrypted SecretStore fixture.

    Returns:
        None.
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

    runtime = ProviderRuntimeFactory(
        ProviderRuntimeResolver(repository, secret_store)
    ).build_llm()

    assert runtime.config_version_id == "provider-llm-runtime-v1"
    assert runtime.adapter.descriptor.config["base_url"] == "https://api.deepseek.com"
    assert runtime.adapter.descriptor.config["model"] == "deepseek-v4-pro"
    assert "runtime-secret" not in repr(runtime)


def test_runtime_factory_builds_llm_from_active_provider_category(
    secret_store: SecretStore,
) -> None:
    """LLM runtime should resolve active DeepSeek configs by category."""
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

    runtime = ProviderRuntimeFactory(
        ProviderRuntimeResolver(repository, secret_store)
    ).build_llm()

    assert runtime.config_version_id == "provider-deepseek-active"
    assert runtime.adapter.descriptor.config["base_url"] == "https://api.deepseek.com/v1"
    assert runtime.adapter.descriptor.config["model"] == "deepseek-chat"


def test_runtime_factory_builds_embedding_from_active_provider_category(
    secret_store: SecretStore,
) -> None:
    """Embedding runtime should resolve active provider configs by category."""
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
    assert runtime.adapter.descriptor.config["base_url"] == (
        "https://api.jina.ai/v1/embeddings"
    )
    assert runtime.adapter.descriptor.config["model"] == "jina-embeddings-v3"
