"""Shared pytest fixtures for the Margin test suite.

This module provides reusable fixtures that tests across the codebase can depend on,
such as pre-configured database URLs for integration testing.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def database_url() -> str:
    """Return the PostgreSQL integration-test URL.

    Returns:
        The database URL from the ``MARGIN_DATABASE_URL`` environment variable,
        falling back to a local development PostgreSQL instance.
    """
    return os.getenv(
        "MARGIN_DATABASE_URL",
        "postgresql+psycopg://margin:margin@localhost:5432/margin",
    )
