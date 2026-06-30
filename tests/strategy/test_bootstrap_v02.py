"""Idempotent production configuration bootstrap tests.

This module validates that the strategy bootstrap service creates default
configuration idempotently, handles missing required providers gracefully,
and tolerates optional provider health failures.
"""

from __future__ import annotations

import os

from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.bootstrap import (
    ProviderBootstrapSpec,
    StrategyBootstrapService,
)
from margin.strategy.provider_config import ProviderConfigHealthService
from margin.strategy.repository import MemoryStrategyRepository
from margin.strategy.service import StrategyService


def test_bootstrap_creates_one_executable_default_scope_idempotently(
    database_url: str,
) -> None:
    """Verify bootstrap produces an active base config without duplicating versions.

    Running bootstrap twice with the same inputs must yield the same scope
    version and exactly one of each configuration entity.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    repository = MemoryStrategyRepository()
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={"akshare": lambda _config, _secret: None},
    )
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
        health_service=health_service,
    )
    providers = (
        ProviderBootstrapSpec(
            provider_name="akshare",
            provider_type="market_data",
            secret_required=False,
        ),
    )

    first = bootstrap.ensure_defaults(
        member_security_ids=("sec-1", "sec-2"),
        providers=providers,
        required_provider_names=("akshare",),
    )
    second = bootstrap.ensure_defaults(
        member_security_ids=("sec-1", "sec-2"),
        providers=providers,
        required_provider_names=("akshare",),
    )

    assert first.scope_version_id == "scope-default-v0.2.0"
    assert second.scope_version_id == first.scope_version_id
    assert len(repository.list_provider_configs("local-admin")) == 1
    assert len(repository.list_universe_definitions("local-admin")) == 1
    assert len(repository.list_research_scopes("local-admin")) == 1
    assert repository.get_active_research_scope("local-admin") is not None
    engine.dispose()


def test_bootstrap_does_not_activate_scope_when_required_provider_is_missing() -> None:
    """Verify a partial Provider setup remains visible but is not executable.

    When a required provider is absent, the scope version must not be created
    and the missing provider names must be reported.

    Returns:
        None.
    """
    repository = MemoryStrategyRepository()
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
    )

    result = bootstrap.ensure_defaults(
        member_security_ids=("sec-1",),
        providers=(),
        required_provider_names=("llm",),
    )

    assert result.scope_version_id is None
    assert result.missing_provider_names == ("llm",)
    assert repository.get_active_research_scope("local-admin") is None


def test_optional_provider_health_failure_does_not_abort_bootstrap(
    database_url: str,
) -> None:
    """Verify a failed optional adapter stays in review while base config remains usable.

    A failing optional provider health check must not abort the bootstrap;
    the provider config should remain in review state.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(create_session_factory(engine)),
        master_key=os.urandom(32),
    )
    repository = MemoryStrategyRepository()
    health_service = ProviderConfigHealthService(
        repository,
        secret_store,
        health_adapters={
            "akshare": lambda _config, _secret: (_ for _ in ()).throw(
                RuntimeError("upstream unavailable")
            )
        },
    )
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=StrategyService(repository=repository),
        health_service=health_service,
    )

    result = bootstrap.ensure_defaults(
        member_security_ids=("sec-1",),
        providers=(
            ProviderBootstrapSpec(
                provider_name="akshare",
                provider_type="market_data",
                secret_required=False,
            ),
        ),
        required_provider_names=("llm",),
    )

    assert result.scope_version_id is None
    assert repository.get_provider_config(
        "provider-akshare-default-v0.2.0"
    ).lifecycle.value == "review"
    engine.dispose()
