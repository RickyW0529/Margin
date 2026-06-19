"""Safety tests for PostgreSQL integration-test isolation."""

from __future__ import annotations

import pytest

from tests.conftest import resolve_test_database_url


def test_test_database_defaults_to_dedicated_database(monkeypatch):
    monkeypatch.delenv("MARGIN_TEST_DATABASE_URL", raising=False)

    url = resolve_test_database_url()

    assert url.endswith("/margin_test")


def test_test_database_rejects_development_database(monkeypatch):
    monkeypatch.setenv(
        "MARGIN_TEST_DATABASE_URL",
        "postgresql+psycopg://margin:margin@localhost:5432/margin",
    )

    with pytest.raises(RuntimeError, match="dedicated test database"):
        resolve_test_database_url()
