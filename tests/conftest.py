"""Shared pytest fixtures for the Margin test suite.

This module provides reusable fixtures that tests across the codebase can depend on,
such as pre-configured database URLs for integration testing.
"""

from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://margin:margin@localhost:5432/margin_test"
)


def resolve_test_database_url() -> str:
    """Resolve and validate the dedicated PostgreSQL test database URL."""
    url = os.getenv("MARGIN_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    database_name = make_url(url).database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise RuntimeError("test database name contains unsupported characters")
    if not (
        database_name.endswith("_test")
        or database_name.startswith("test_")
    ):
        raise RuntimeError(
            "MARGIN_TEST_DATABASE_URL must point to a dedicated test database"
        )
    return url


TEST_DATABASE_URL = resolve_test_database_url()
os.environ["MARGIN_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["MARGIN_ENVIRONMENT"] = "test"
os.environ["MARGIN_LLM_API_KEY"] = ""
os.environ["MARGIN_EMBEDDING_API_KEY"] = ""
os.environ["MARGIN_WEBSEARCH_API_KEY"] = ""


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database() -> None:
    """Create the isolated test database when the local PostgreSQL user permits it."""
    test_url = make_url(TEST_DATABASE_URL)
    database_name = test_url.database
    assert database_name is not None
    admin_engine = create_engine(
        test_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar_one_or_none()
            if exists is None:
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin_engine.dispose()

    test_engine = create_engine(TEST_DATABASE_URL)
    try:
        with test_engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        test_engine.dispose()


@pytest.fixture
def database_url() -> str:
    """Return the PostgreSQL integration-test URL.

    Returns:
        The database URL from the ``MARGIN_DATABASE_URL`` environment variable,
        falling back to a local development PostgreSQL instance.
    """
    return TEST_DATABASE_URL
