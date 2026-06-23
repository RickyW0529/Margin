"""Runtime resolution tests for active versioned Provider configuration."""

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
    """Return an isolated encrypted Secret Store."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    repository = SQLAlchemySecretRepository(create_session_factory(engine))
    return SecretStore(repository, master_key=os.urandom(32))


def test_runtime_resolves_only_active_config_and_frozen_secret(
    secret_store: SecretStore,
) -> None:
    """Runtime consumers receive the active config and its exact secret version."""
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
    """Draft configuration is not executable."""
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
    """Providers such as AKShare may be explicitly configured as secretless."""
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
    """Factory output preserves the exact active config version used."""
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
