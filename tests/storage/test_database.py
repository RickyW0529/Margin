"""Tests for database configuration and connectivity.

This module verifies that database settings are read correctly from the
environment and from ``MarginSettings``, and that SQLAlchemy engines and
session factories can connect to PostgreSQL and execute simple queries.
"""

from __future__ import annotations

from sqlalchemy import text

from margin.settings import MarginSettings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_database_settings_reads_environment(monkeypatch):
    """Verify that ``DatabaseSettings`` reads the PostgreSQL URL from the environment.

    Args:
        monkeypatch: Any: .

    Returns:
        Any: .
    """
    url = "postgresql+psycopg://margin:margin@localhost:5432/margin"
    monkeypatch.setenv("MARGIN_DATABASE_URL", url)
    monkeypatch.setenv("MARGIN_DATABASE_ECHO", "true")
    monkeypatch.setenv("MARGIN_DATABASE_POOL_PRE_PING", "false")
    monkeypatch.setenv("MARGIN_DATABASE_POOL_SIZE", "6")
    monkeypatch.setenv("MARGIN_DATABASE_STATEMENT_TIMEOUT_MS", "23456")

    settings = DatabaseSettings.from_env()

    assert settings.url == url
    assert settings.echo is True
    assert settings.pool_pre_ping is False
    assert settings.pool_size == 6
    assert settings.statement_timeout_ms == 23_456


def test_database_settings_can_be_built_from_margin_settings():
    """Verify ``DatabaseSettings`` can be constructed from a ``MarginSettings`` instance.

    Returns:
        Any: .
    """
    margin_settings = MarginSettings(
        _env_file=None,
        database_url="postgresql+psycopg://margin:margin@localhost:5432/margin",
        database_echo=True,
        database_pool_pre_ping=False,
        database_pool_size=7,
        database_statement_timeout_ms=12_345,
    )

    settings = DatabaseSettings.from_settings(margin_settings)

    assert settings.url == str(margin_settings.database_url)
    assert settings.echo is True
    assert settings.pool_pre_ping is False
    assert settings.pool_size == 7
    assert settings.statement_timeout_ms == 12_345


def test_create_database_engine_applies_pool_and_statement_timeout(monkeypatch):
    """Verify engine creation forwards pool and PostgreSQL timeout settings.

    Args:
        monkeypatch: Any: .

    Returns:
        Any: .
    """
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        """Process fake_create_engine.

        Args:
            url: str: .
            **kwargs: object: .

        Returns:
            object: .
        """
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("margin.storage.database.create_engine", fake_create_engine)

    engine = create_database_engine(
        DatabaseSettings(
            url="postgresql+psycopg://margin:margin@localhost:5432/margin",
            pool_size=3,
            statement_timeout_ms=4_567,
        )
    )

    assert engine is not None
    assert captured["url"] == "postgresql+psycopg://margin:margin@localhost:5432/margin"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["pool_size"] == 3
    assert kwargs["connect_args"] == {"options": "-c statement_timeout=4567"}


def test_session_factory_connects_to_postgres(database_url):
    """Verify that a session factory can execute a simple query against PostgreSQL.

    Args:
        database_url: Any: .

    Returns:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert session.scalar(text("select 1")) == 1

    engine.dispose()
