"""Alembic migration environment."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from margin.core import db_audit as core_db_audit  # noqa: F401
from margin.dashboard import db_models as dashboard_db_models  # noqa: F401
from margin.evidence import db_models as evidence_db_models  # noqa: F401
from margin.holdings_monitoring import db_models as monitoring_db_models  # noqa: F401
from margin.news import db_models as news_db_models  # noqa: F401
from margin.portfolio import db_models as portfolio_db_models  # noqa: F401
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings
from margin.strategy import db_models as strategy_db_models  # noqa: F401
from margin.vector import db_models as vector_db_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", DatabaseSettings.from_env().url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""
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
    """Run migrations with a live PostgreSQL connection."""
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
