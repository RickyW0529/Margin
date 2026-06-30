"""Incremental acquisition runner and outbox publisher tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.news.db_models import (
    DocumentEventRow,
    DocumentOutboxRow,
    SourceCursorRow,
)
from margin.news.discovery import DiscoveredDocument
from margin.news.models import DocumentStatus, SourceLevel, make_document_event
from margin.news.outbox import DocumentEventPublisher, OutboxConsumer
from margin.news.repository import NewsRepository
from margin.news.scheduler import IncrementalAcquisitionRunner
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory


@pytest.fixture
def news_repository(database_url):
    """Create clean scheduler tables."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DocumentOutboxRow, DocumentEventRow, SourceCursorRow):
            session.query(row).delete()
    yield NewsRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeConnector:
    """Fake discovery connector that returns one document on the first call.

    Attributes:
        cursors: List of cursor values passed to each ``discover`` call.
    """
    def __init__(self):
        """Initialize the fake connector with an empty cursor list."""
        self.cursors: list[str | None] = []

    def discover(self, cursor: str | None, limit: int):
        """Return one discovered document or an empty list when cursor matches.

        Args:
            cursor: The cursor to resume discovery from.
            limit: Maximum number of documents to return.

        Returns:
            A list of ``DiscoveredDocument`` instances (zero or one).
        """
        self.cursors.append(cursor)
        if cursor == "cursor-1":
            return []
        return [
            DiscoveredDocument(
                external_id="doc-1",
                title="公告",
                source_url="https://example.com/a",
                published_at=datetime(2026, 6, 18, tzinfo=UTC),
                cursor="cursor-1",
            )
        ]


class FakeAcquirer:
    """Fake acquirer that returns a durable L1 document event."""
    def acquire(self, source_name: str, url: str, title_override=None, published_at=None):
        """Return a document event with L1 source level for the given URL.

        Args:
            source_name: The source name to assign to the event.
            url: The source URL for the document.
            title_override: Optional title override; defaults to ``"公告"``.
            published_at: Optional publication timestamp.

        Returns:
            A ``DocumentEvent`` with seeded content and symbols.
        """
        return make_document_event(
            source_url=url,
            source_name=source_name,
            source_level=SourceLevel.L1,
            title=title_override or "公告",
            content="正文",
            published_at=published_at,
        )


def test_incremental_runner_advances_cursor_and_publishes_ready_events(news_repository):
    """Runner must persist events, enqueue ready documents, and advance cursor once handled."""
    connector = FakeConnector()
    runner = IncrementalAcquisitionRunner(
        repository=news_repository,
        acquirer=FakeAcquirer(),
        publisher=DocumentEventPublisher(news_repository),
    )

    result = runner.run_once("sse", connector, limit=10)

    assert result.discovered == 1
    assert result.published == 1
    assert news_repository.get_cursor("sse", "announcements") == "cursor-1"
    assert len(news_repository.claim_outbox("vector_index", limit=10)) == 1

    runner.run_once("sse", connector, limit=10)
    assert connector.cursors == [None, "cursor-1"]


def test_publisher_persists_parse_failed_without_outbox(news_repository):
    """Publisher must keep parse failures auditable but not indexable."""
    failed = make_document_event(
        source_url="https://example.com/fail",
        source_name="sse",
        source_level=SourceLevel.L1,
        title="失败公告",
        processing_status=DocumentStatus.PARSE_FAILED,
        processing_error="parse failed",
    )
    publisher = DocumentEventPublisher(news_repository)

    publisher.persist_pending(failed)

    consumer = OutboxConsumer(news_repository)
    assert news_repository.get_document_event(failed.event_id) == failed
    assert consumer.claim_batch("vector_index", limit=10) == []
