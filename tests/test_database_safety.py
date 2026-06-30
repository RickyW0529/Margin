"""Safety tests for PostgreSQL integration-test isolation.

Verifies that the test database resolver defaults to a dedicated ``margin_test``
database and rejects connections to the development database.
"""

from __future__ import annotations

import pytest

from tests.conftest import resolve_test_database_url


def test_test_database_defaults_to_dedicated_database(monkeypatch):
    """Test that the database URL defaults to a dedicated test database.

    Args:
        monkeypatch: Pytest fixture for modifying environment variables.
    """
    monkeypatch.delenv("MARGIN_TEST_DATABASE_URL", raising=False)

    url = resolve_test_database_url()

    assert url.endswith("/margin_test")


def test_test_database_rejects_development_database(monkeypatch):
    """Test that the resolver rejects a URL pointing at the development database.

    Args:
        monkeypatch: Pytest fixture for modifying environment variables.
    """
    monkeypatch.setenv(
        "MARGIN_TEST_DATABASE_URL",
        "postgresql+psycopg://margin:margin@localhost:5432/margin",
    )

    with pytest.raises(RuntimeError, match="dedicated test database"):
        resolve_test_database_url()
