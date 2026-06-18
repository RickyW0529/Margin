"""SQLAlchemy database configuration for PostgreSQL.

This module provides immutable connection settings and helper functions for creating a
shared SQLAlchemy engine and a bound session factory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://margin:margin@localhost:5432/margin"
"""Default SQLAlchemy connection URL used when no environment override is provided."""

SessionFactory = sessionmaker[Session]
"""Typed alias for a SQLAlchemy session factory bound to an engine."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Immutable PostgreSQL database connection settings.

    Attributes:
        url: Fully-qualified SQLAlchemy database URL.
        echo: Whether SQLAlchemy logs every emitted SQL statement.
        pool_pre_ping: Whether to verify connections before checking them out from the pool.
    """

    url: str = DEFAULT_DATABASE_URL
    echo: bool = False
    pool_pre_ping: bool = True

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Load connection settings from environment variables.

        The following environment variables are recognized:

        * ``MARGIN_DATABASE_URL`` - database URL (defaults to :data:`DEFAULT_DATABASE_URL`).
        * ``MARGIN_DATABASE_ECHO`` - enable SQL echoing when set to ``"1"``, ``"true"``,
          or ``"yes"``.

        Returns:
            DatabaseSettings: Settings populated from the process environment.
        """
        return cls(
            url=os.getenv("MARGIN_DATABASE_URL", DEFAULT_DATABASE_URL),
            echo=os.getenv("MARGIN_DATABASE_ECHO", "").lower() in {"1", "true", "yes"},
        )


def create_database_engine(settings: DatabaseSettings | None = None) -> Engine:
    """Create the shared SQLAlchemy engine.

    Args:
        settings: Database connection settings. If ``None``, settings are loaded from the
            environment via :meth:`DatabaseSettings.from_env`.

    Returns:
        Engine: Configured SQLAlchemy engine bound to the resolved settings.
    """
    resolved = settings or DatabaseSettings.from_env()
    return create_engine(
        resolved.url,
        echo=resolved.echo,
        pool_pre_ping=resolved.pool_pre_ping,
    )


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create a typed session factory bound to the given engine.

    Args:
        engine: SQLAlchemy engine that the produced sessions will use.

    Returns:
        SessionFactory: A ``sessionmaker`` factory configured with ``expire_on_commit=False``.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
