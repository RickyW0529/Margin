"""Tests for application bootstrap container wiring."""

from __future__ import annotations

from margin.bootstrap.container import AppContainer
from margin.settings import MarginSettings
from margin.strategy.provider_runtime import ProviderRuntimeFactory
from margin.strategy.repository import SQLAlchemyStrategyRepository


def _settings() -> MarginSettings:
    """Helper settings.

    Returns:
        MarginSettings: .
    """
    return MarginSettings(
        _env_file=None,
        database_url="postgresql+psycopg://margin:margin@localhost:5432/margin_test",
        secret_master_key="!" * 32,
    )


def test_app_container_exposes_shared_runtime_services() -> None:
    """Verify bootstrap wiring lives outside the FastAPI dependency layer.

    Returns:
        None: .
    """
    container = AppContainer(_settings())
    try:
        assert container.engine is container.engine
        assert container.session_factory is container.session_factory
        assert isinstance(container.strategy_repository, SQLAlchemyStrategyRepository)
        assert isinstance(container.provider_runtime_factory, ProviderRuntimeFactory)
    finally:
        container.dispose()


def test_app_container_dispose_does_not_create_unused_engine(monkeypatch) -> None:
    """Shutdown should not initialize database resources that were never used.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """

    def fail_if_called(*_args, **_kwargs):
        """Process fail_if_called.

        Args:
            *_args: Any: .
            **_kwargs: Any: .

        Returns:
            Any: .
        """
        raise AssertionError("dispose() created an unused engine")

    monkeypatch.setattr(
        "margin.bootstrap.container.create_database_engine",
        fail_if_called,
    )

    AppContainer(_settings()).dispose()
