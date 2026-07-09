"""v0.2 indexing outbox lease and retry recovery tests.

Verifies that expired processing leases can be reclaimed by the indexing runner
and that embedding failures after successful parsing keep the outbox entry in a
retryable state rather than marking it permanently failed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from margin.news.db_models import DocumentEventRow, DocumentOutboxRow
from margin.news.models import SourceLevel, make_document_event
from margin.news.repository import NewsRepository
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.indexing_runner import IndexingRunner


@pytest.fixture
def news_repository(database_url: str) -> Iterator[NewsRepository]:
    """Yield a ``NewsRepository`` seeded with a single document event.

    Args:
        database_url: str: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DocumentOutboxRow, DocumentEventRow):
            session.query(row).delete()
    repo = NewsRepository(session_factory)
    event = make_document_event(
        source_url="https://example.com/a",
        source_name="sse",
        source_level=SourceLevel.L1,
        title="公告",
        content="正文",
    ).model_copy(update={"event_id": "event-1", "document_id": "doc-1"})
    repo.add_document_event(event, publishable=False)
    yield repo
    Base.metadata.drop_all(engine)
    engine.dispose()


class FailingPipeline:
    """Stub pipeline that always raises to simulate embedding provider failure.."""

    def index_event(self, event) -> None:  # noqa: ANN001
        """Raise a runtime error simulating embedding provider unavailability.

        Args:
            event: Any: .

        Returns:
            None: .
        """
        raise RuntimeError("embedding provider unavailable")


def test_expired_processing_lease_can_be_reclaimed(
    news_repository: NewsRepository,
) -> None:
    """Expired processing leases must be reclaimable by the indexing runner.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    outbox_id = news_repository.add_document_outbox(
        event_id="event-1",
        topic="vector_index",
        status="processing",
        claimed_at=datetime(2026, 6, 22, tzinfo=UTC) - timedelta(minutes=30),
    )
    runner = IndexingRunner(
        news_repository=news_repository,
        pipeline=FailingPipeline(),
        lease_seconds=300,
    )

    claimed = runner.claim_next(now=datetime(2026, 6, 22, tzinfo=UTC))

    assert claimed is not None
    assert claimed.outbox_id == outbox_id


def test_parser_success_embedding_failure_keeps_retryable_outbox(
    news_repository: NewsRepository,
) -> None:
    """Embedding failure after successful parsing must keep the outbox retryable.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    news_repository.add_document_outbox(
        event_id="event-1",
        topic="vector_index",
        status="pending",
    )
    runner = IndexingRunner(news_repository=news_repository, pipeline=FailingPipeline())

    runner.process_one(event_id="event-1")

    row = news_repository.get_outbox_by_event("event-1", "vector_index")
    assert row is not None
    assert row.status == "failed_retryable"
