#!/usr/bin/env python3
"""Verify Alembic migrations against a clean PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

from alembic import command
from margin.settings import DEFAULT_DATABASE_URL, get_settings
from margin.sql.health_queries import (
    alembic_version,
    non_system_tables,
    pgvector_extension,
)
from margin.sql.raw_statements import TERMINATE_DATABASE_CONNECTIONS


@dataclass(frozen=True)
class MigrationVerificationResult:
    """Serializable migration verification result."""

    database_name: str
    expected_head: str
    current_head: str | None
    failed_revision: str | None
    tables: tuple[str, ...]
    pgvector_available: bool


@contextmanager
def _temporary_database_url(database_url: str | URL) -> Iterator[str]:
    """temporary database url."""
    previous = os.environ.get("MARGIN_DATABASE_URL")
    rendered = (
        database_url.render_as_string(hide_password=False)
        if isinstance(database_url, URL)
        else database_url
    )
    os.environ["MARGIN_DATABASE_URL"] = rendered
    get_settings.cache_clear()
    try:
        yield rendered
    finally:
        if previous is None:
            os.environ.pop("MARGIN_DATABASE_URL", None)
        else:
            os.environ["MARGIN_DATABASE_URL"] = previous
        get_settings.cache_clear()


def _script_head() -> str:
    """script head."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def _terminate_database(admin_url: URL, database_name: str) -> None:
    """terminate database."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(
                TERMINATE_DATABASE_CONNECTIONS,
                {"database_name": database_name},
            )
    finally:
        engine.dispose()


def _drop_database(admin_url: URL, database_name: str) -> None:
    """drop database."""
    _terminate_database(admin_url, database_name)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        engine.dispose()


def _create_database(admin_url: URL, database_name: str) -> None:
    """create database."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        engine.dispose()


def _install_pgvector(target_url: URL) -> bool:
    """install pgvector."""
    engine = create_engine(target_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            return (
                connection.execute(
                    pgvector_extension()
                ).scalar()
                == 1
            )
    finally:
        engine.dispose()


def _inspect_database(target_url: URL) -> tuple[str | None, tuple[str, ...], bool]:
    """inspect database."""
    engine = create_engine(target_url)
    try:
        with engine.connect() as connection:
            current_head = connection.execute(
                alembic_version()
            ).scalar()
            table_rows = connection.execute(
                non_system_tables()
            ).all()
            tables = tuple(
                sorted(
                    table_name
                    if schema_name == "public"
                    else f"{schema_name}.{table_name}"
                    for schema_name, table_name in table_rows
                )
            )
            pgvector_available = (
                connection.execute(
                    pgvector_extension()
                ).scalar()
                == 1
            )
            return current_head, tables, pgvector_available
    finally:
        engine.dispose()


def verify_clean_database(
    database_url: str = DEFAULT_DATABASE_URL,
    *,
    database_name: str | None = None,
    drop_existing: bool = False,
    keep_database: bool = False,
) -> MigrationVerificationResult:
    """Create a clean database, run all migrations, inspect, and clean up."""
    url = make_url(database_url)
    base_name = database_name or f"{url.database}_migration_{uuid.uuid4().hex[:8]}"
    admin_url = url.set(database="postgres")
    target_url = url.set(database=base_name)
    expected_head = _script_head()
    failed_revision: str | None = None
    current_head: str | None = None
    tables: tuple[str, ...] = ()
    pgvector_available = False
    if drop_existing:
        _drop_database(admin_url, base_name)
    try:
        _create_database(admin_url, base_name)
        pgvector_available = _install_pgvector(target_url)
        with _temporary_database_url(target_url):
            config = Config("alembic.ini")
            command.upgrade(config, "head")
        current_head, tables, pgvector_available = _inspect_database(target_url)
    except Exception as exc:  # noqa: BLE001
        failed_revision = type(exc).__name__
        raise
    finally:
        if not keep_database:
            _drop_database(admin_url, base_name)
    return MigrationVerificationResult(
        database_name=base_name,
        expected_head=expected_head,
        current_head=current_head,
        failed_revision=failed_revision,
        tables=tables,
        pgvector_available=pgvector_available,
    )


def main(argv: list[str] | None = None) -> int:
    """main."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("MARGIN_DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument("--database-name")
    parser.add_argument("--drop-existing", action="store_true")
    parser.add_argument("--keep-database", action="store_true")
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)
    try:
        result = verify_clean_database(
            args.database_url,
            database_name=args.database_name,
            drop_existing=args.drop_existing,
            keep_database=args.keep_database,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "error_code": type(exc).__name__}))
        return 1
    payload = {"status": "ok", **asdict(result)}
    output = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)
    return 0 if result.current_head == result.expected_head else 1


if __name__ == "__main__":
    sys.exit(main())
