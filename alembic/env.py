"""Alembic migration environment.

Configures the Alembic migration context for the Margin project, importing
every SQLAlchemy model package so that ``Base.metadata`` reflects all tables
before autogenerate or migration execution. The database URL is injected from
application settings at runtime.

Imports of model modules are intentionally side-effect only (marked with
``noqa: F401``) so Alembic can register them on the shared ``Base.metadata``.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from margin.config_runtime import db_models as config_runtime_db_models  # noqa: F401
from margin.core import db_audit as core_db_audit  # noqa: F401
from margin.core import db_orchestration as core_db_orchestration  # noqa: F401
from margin.dashboard import db_models as dashboard_db_models  # noqa: F401
from margin.data import db_models as data_db_models  # noqa: F401
from margin.evidence import db_models as evidence_db_models  # noqa: F401
from margin.news import db_models as news_db_models  # noqa: F401
from margin.settings import get_settings
from margin.storage.base import Base
from margin.strategy import db_models as strategy_db_models  # noqa: F401
from margin.vector import db_models as vector_db_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a live Engine.

    Generates SQL statements from the migration script using literal binds and
    emits them without an active database connection. Suitable for producing
    SQL scripts for offline review or external execution.

    Returns:
        None.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live PostgreSQL connection.

    Creates a transient SQLAlchemy Engine (``NullPool``) from the Alembic
    configuration, opens a connection, and executes the migration script
    inside a single transaction.

    Returns:
        None.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
