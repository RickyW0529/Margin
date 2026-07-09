"""Shared application service container for runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from sqlalchemy import Engine

from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.settings import MarginSettings
from margin.storage.database import (
    DatabaseSettings,
    SessionFactory,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.provider_runtime import (
    ProviderRuntimeFactory,
    ProviderRuntimeResolver,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService


@dataclass(frozen=True)
class AppContainer:
    """Process-level container for shared database-backed runtime services.."""

    settings: MarginSettings

    @cached_property
    def engine(self) -> Engine:
        """Return the shared SQLAlchemy engine.

        Returns:
            Engine: .
        """
        return create_database_engine(DatabaseSettings.from_settings(self.settings))

    @cached_property
    def session_factory(self) -> SessionFactory:
        """Return the shared SQLAlchemy session factory.

        Returns:
            SessionFactory: .
        """
        return create_session_factory(self.engine)

    @cached_property
    def strategy_repository(self) -> SQLAlchemyStrategyRepository:
        """Return the versioned strategy configuration repository.

        Returns:
            SQLAlchemyStrategyRepository: .
        """
        return SQLAlchemyStrategyRepository(self.session_factory)

    @cached_property
    def strategy_service(self) -> StrategyService:
        """Return the versioned strategy configuration service.

        Returns:
            StrategyService: .
        """
        return StrategyService(repository=self.strategy_repository)

    @cached_property
    def secret_store(self) -> SecretStore:
        """Return the encrypted provider Secret Store.

        Returns:
            SecretStore: .
        """
        return SecretStore(
            SQLAlchemySecretRepository(self.session_factory),
            master_key=self.settings.secret_master_key.get_secret_value(),
            key_version=self.settings.secret_key_version,
        )

    @cached_property
    def provider_runtime_factory(self) -> ProviderRuntimeFactory:
        """Return the active-config Provider runtime factory.

        Returns:
            ProviderRuntimeFactory: .
        """
        return ProviderRuntimeFactory(
            ProviderRuntimeResolver(
                self.strategy_repository,
                self.secret_store,
            )
        )

    def dispose(self) -> None:
        """Dispose the shared engine when a process shuts down.

        Returns:
            None: .
        """
        if "engine" in self.__dict__:
            self.engine.dispose()
