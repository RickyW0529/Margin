"""SQLAlchemy database configuration for PostgreSQL.

This module provides immutable connection settings and helper functions for creating a
shared SQLAlchemy engine and a bound session factory.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from margin.settings import DEFAULT_DATABASE_URL as SETTINGS_DEFAULT_DATABASE_URL
from margin.settings import MarginSettings

DEFAULT_DATABASE_URL = SETTINGS_DEFAULT_DATABASE_URL
"""Default SQLAlchemy connection URL used when no environment override is provided."""

SessionFactory = sessionmaker[Session]
"""Typed alias for a SQLAlchemy session factory bound to an engine."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Immutable PostgreSQL database connection settings.."""

    url: str = DEFAULT_DATABASE_URL
    echo: bool = False
    pool_pre_ping: bool = True
    pool_size: int = 10
    statement_timeout_ms: int = 30_000

    @classmethod
    def from_settings(cls, settings: MarginSettings) -> DatabaseSettings:
        """Build database settings from centralized application settings.

        Args:
            settings: MarginSettings: .

        Returns:
            DatabaseSettings: .
        """
        return cls(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
            pool_size=settings.database_pool_size,
            statement_timeout_ms=settings.database_statement_timeout_ms,
        )

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Load connection settings through :class:`MarginSettings`.

        Returns:
            DatabaseSettings: .
        """
        return cls.from_settings(MarginSettings())


def create_database_engine(settings: DatabaseSettings | None = None) -> Engine:
    """Create the shared SQLAlchemy engine.

    Args:
        settings: DatabaseSettings | None: .

    Returns:
        Engine: .
    """
    resolved = settings or DatabaseSettings.from_env()
    engine_options: dict[str, object] = {
        "echo": resolved.echo,
        "pool_pre_ping": resolved.pool_pre_ping,
    }
    if _is_postgresql_url(resolved.url):
        engine_options["pool_size"] = resolved.pool_size
        engine_options["connect_args"] = {
            "options": f"-c statement_timeout={resolved.statement_timeout_ms}",
        }
    return create_engine(resolved.url, **engine_options)


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create a typed session factory bound to the given engine.

    Args:
        engine: Engine: .

    Returns:
        SessionFactory: .
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def _is_postgresql_url(url: str) -> bool:
    """Return whether a SQLAlchemy URL targets PostgreSQL.

    Args:
        url: str: .

    Returns:
        bool: .
    """
    return make_url(url).get_backend_name() == "postgresql"
