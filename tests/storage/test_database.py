"""Tests for database configuration and connectivity.

This module verifies that database settings are read correctly from the environment
and that SQLAlchemy engines and session factories can connect to PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import text

from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_database_settings_reads_environment(monkeypatch):
    """Verify that ``DatabaseSettings`` reads the PostgreSQL URL from the environment.

    The test patches ``MARGIN_DATABASE_URL`` and asserts that ``DatabaseSettings.from_env``
    returns a settings object with the expected URL.

    Args:
        monkeypatch: Pytest fixture for temporarily modifying environment variables.
    """
    url = "postgresql+psycopg://margin:margin@localhost:5432/margin"
    monkeypatch.setenv("MARGIN_DATABASE_URL", url)

    settings = DatabaseSettings.from_env()

    assert settings.url == url


def test_session_factory_connects_to_postgres(database_url):
    """Verify that a session factory can execute a simple query against PostgreSQL.

    The test creates an engine and a session factory, runs ``select 1``, and ensures
    the returned scalar value is ``1``.

    Args:
        database_url: Fixture providing the PostgreSQL integration-test URL.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert session.scalar(text("select 1")) == 1

    engine.dispose()
