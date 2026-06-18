"""Tests for persistent deduplication using PostgreSQL.

These tests verify that ``PersistentNewsProcessor`` stores vector-similarity
deduplication decisions and repost-chain edges in PostgreSQL so that state
survives process restarts.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentOutboxRow,
    RepostEdgeRow,
)
from margin.news.dedup import PersistentNewsProcessor
from margin.news.models import SourceLevel, compute_content_hash, make_document_event
from margin.news.repository import NewsRepository
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory


@pytest.fixture
def news_repository(database_url):
    """Create a clean repository with dedup tables.

    Args:
        database_url: SQLAlchemy database URL injected by pytest.

    Yields:
        A ``NewsRepository`` instance backed by a fresh set of dedup tables.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (RepostEdgeRow, DedupRecordRow, DocumentOutboxRow, DocumentEventRow):
            session.query(row).delete()
    yield NewsRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _event(event_id: str, url: str, source_level: SourceLevel = SourceLevel.L4):
    """Build a document event fixture for deduplication tests.

    Args:
        event_id: Unique identifier for the event.
        url: Source URL for the document.
        source_level: Authority level assigned to the source.

    Returns:
        A ``DocumentEvent`` with a deterministic document id and content hash.
    """
    event = make_document_event(
        source_url=url,
        source_name="media",
        source_level=source_level,
        title=f"{event_id} 标题",
        content=f"{event_id} 正文内容",
        content_hash=compute_content_hash(f"{event_id}:{url}"),
        published_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    return event.model_copy(update={"event_id": event_id, "document_id": f"doc_{event_id}"})


def test_persistent_processor_uses_vector_similarity_after_restart(news_repository):
    """Vector similarity deduplication survives a process restart.

    Verifies that:
    - a duplicate event is linked to its canonical event via vector similarity;
    - the dedup reason is persisted in PostgreSQL;
    - a second processor instance can continue the repost chain from stored state.
    """
    canonical = _event("evt_canonical", "https://exchange.example/a", SourceLevel.L1)
    duplicate = _event("evt_duplicate", "https://media.example/a", SourceLevel.L4)
    news_repository.add_document_event(canonical, publishable=False)

    first_processor = PersistentNewsProcessor(
        news_repository,
        vector_similarity_func=lambda incoming, existing: 0.97,
        vector_similarity_threshold=0.95,
    )
    result = first_processor.process([duplicate])

    assert result.duplicate_count == 1
    assert result.duplicates[0]["duplicate_of"] == canonical.event_id

    restarted_processor = PersistentNewsProcessor(
        news_repository,
        vector_similarity_func=lambda incoming, existing: 0.97,
        vector_similarity_threshold=0.95,
    )
    second_duplicate = _event("evt_duplicate_2", "https://media.example/b", SourceLevel.L4)
    restarted_processor.process([second_duplicate])

    assert news_repository.get_dedup_record(duplicate.event_id).reason == "vector_similarity"
    assert [
        edge.child_event_id for edge in news_repository.list_repost_chain(canonical.event_id)
    ] == [duplicate.event_id, second_duplicate.event_id]
