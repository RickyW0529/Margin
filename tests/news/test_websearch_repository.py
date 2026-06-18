"""Tests for ``WebSearchService`` persistence and acquisition.

These tests verify that the web search service persists search queries and
results before attempting to fetch originals, so rejected paywalled or
inaccessible originals still leave a complete audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.news.acquirer import BaseConnector, SnapshotStore, SourceDescriptor, SourceRegistry
from margin.news.db_models import (
    SearchQueryRow,
    SearchResultRow,
)
from margin.news.models import SourceLevel
from margin.news.repository import NewsRepository
from margin.news.websearch import WebSearchProvider, WebSearchService
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory


@pytest.fixture
def news_repository(database_url):
    """Create a clean repository with search audit tables.

    Args:
        database_url: SQLAlchemy database URL injected by pytest.

    Yields:
        A ``NewsRepository`` instance backed by a fresh set of tables.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(SearchResultRow).delete()
        session.query(SearchQueryRow).delete()
    yield NewsRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_search_results_are_persisted_before_original_verification(
    tmp_path,
    news_repository,
):
    """Search results are persisted even when the original page is inaccessible.

    Verifies that a paywalled connector returns no acquisition events while the
    repository still records the query and each result with the correct
    ``has_accessible_original`` flag.
    """

    class PaywallConnector(BaseConnector):
        """Fake connector that simulates a paywalled original page."""

        @property
        def source_name(self) -> str:
            """Return the source identifier used by the registry."""
            return "websearch"

        def fetch(self, url, **kwargs) -> tuple[bytes, str, int]:
            """Return a paywalled HTML page instead of article content.

            Args:
                url: The URL being fetched.
                **kwargs: Additional fetch options.

            Returns:
                A tuple of raw bytes, content type, and HTTP status code.
            """
            return b"subscribe to read full article", "text/html", 200

    def search(query: str, max_results: int = 10) -> list[dict]:
        """Return a fixed search result for the query.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            A list of raw search result dictionaries.
        """
        return [
            {
                "url": "https://paywall.example/article",
                "title": "Paywalled",
                "snippet": "snippet only",
            }
        ]

    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(
            name="websearch",
            source_type="websearch",
            default_level=SourceLevel.L4,
        ),
        connector=PaywallConnector(),
    )
    provider = WebSearchProvider(search_func=search)
    service = WebSearchService(
        provider,
        registry,
        SnapshotStore(base_dir=tmp_path),
        repository=news_repository,
    )

    record, events = service.search_and_acquire(
        "paywalled query",
        max_results=1,
        searched_at=datetime(2026, 6, 18, tzinfo=UTC),
    )

    assert events == []
    stored = news_repository.get_search_record(record.query_id)
    assert stored is not None
    assert stored.results[0].url == "https://paywall.example/article"
    assert stored.results[0].has_accessible_original is False
