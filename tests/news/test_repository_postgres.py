"""Tests for PostgreSQL-backed persistence in the news repository.

These tests cover cursors, snapshots, document events, outbox delivery, search
records, parse failures, deduplication records, and repost-chain persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.news.db_models import (
    DedupRecordRow,
    DocumentEventRow,
    DocumentOutboxRow,
    RawSnapshotRow,
    RepostEdgeRow,
    SearchQueryRow,
    SearchResultRow,
    SourceCursorRow,
)
from margin.news.models import (
    DocumentStatus,
    RawSnapshot,
    SourceLevel,
    compute_content_hash,
    make_document_event,
)
from margin.news.repository import NewsRepository
from margin.news.websearch import SearchQueryRecord, SearchResult
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def news_repository(database_url):
    """Create a clean repository with all news tables.

    Args:
        database_url: SQLAlchemy database URL injected by pytest.

    Yields:
        A ``NewsRepository`` instance backed by a fresh set of tables.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            RepostEdgeRow,
            DedupRecordRow,
            SearchResultRow,
            SearchQueryRow,
            DocumentOutboxRow,
            DocumentEventRow,
            RawSnapshotRow,
            SourceCursorRow,
        ):
            session.query(row).delete()
    yield NewsRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _snapshot() -> RawSnapshot:
    """Return a fixed raw snapshot fixture.

    Returns:
        A ``RawSnapshot`` with deterministic fields for test records.
    """
    return RawSnapshot(
        snapshot_id="snp_1",
        source_url="https://example.com/a.html",
        content_hash=compute_content_hash("<html>公告</html>".encode()),
        content_type="html",
        raw_size=17,
        storage_path="/snapshots/snp_1.html",
        downloaded_at=datetime(2026, 6, 18, tzinfo=UTC),
        http_status=200,
    )


def _event(event_id: str = "evt_1", url: str = "https://example.com/a.html"):
    """Return a fixed document event fixture.

    Args:
        event_id: Unique identifier for the event.
        url: Source URL for the document.

    Returns:
        A ``DocumentEvent`` with deterministic content, symbols, and snapshot.
    """
    event = make_document_event(
        source_url=url,
        source_name="sse",
        source_level=SourceLevel.L1,
        title="平安银行公告",
        content="000001.SZ 经营现金流改善",
        snapshot_id="snp_1",
        snapshot_hash=_snapshot().content_hash,
        symbols=["000001.SZ"],
        published_at=datetime(2026, 6, 18, tzinfo=UTC),
        available_at=datetime(2026, 6, 18, 1, tzinfo=UTC),
    )
    return event.model_copy(update={"event_id": event_id, "document_id": f"doc_{event_id}"})


def test_repository_persists_cursor_snapshot_event_outbox_and_search(
    news_repository,
):
    """Core repository records survive round-trips and preserve audit fields.

    Verifies that cursors, snapshots, document events, outbox items, and search
    records can be written and read back with identical values.
    """
    repo = news_repository
    snapshot = _snapshot()
    event = _event()
    query = SearchQueryRecord(
        query_id="sq_1",
        query="平安银行 公告",
        api_provider="tavily",
        result_count=1,
        results=(
            SearchResult(
                url="https://example.com/a.html",
                title="公告",
                snippet="摘要",
                has_accessible_original=True,
                content_hash=snapshot.content_hash,
                snapshot_id=snapshot.snapshot_id,
            ),
        ),
        searched_at=datetime(2026, 6, 18, 2, tzinfo=UTC),
    )

    repo.upsert_cursor("sse", "announcements", "2026-06-18T00:00:00Z")
    repo.add_snapshot(snapshot)
    repo.add_document_event(event, publishable=True)
    repo.add_search_record(query)

    assert repo.get_cursor("sse", "announcements") == "2026-06-18T00:00:00Z"
    assert repo.get_snapshot(snapshot.snapshot_id) == snapshot
    assert repo.get_document_event(event.event_id) == event

    claimed = repo.claim_outbox(topic="vector_index", limit=10)
    assert [item.event_id for item in claimed] == [event.event_id]
    repo.mark_outbox_delivered(claimed[0].outbox_id)
    assert repo.claim_outbox(topic="vector_index", limit=10) == []

    stored_query = repo.get_search_record(query.query_id)
    assert stored_query == query


def test_parse_failed_events_are_persisted_but_not_published(news_repository):
    """Parse-failed events are stored but kept out of the publishable outbox.

    Verifies that a document event marked as ``PARSE_FAILED`` is persisted and
    can be retrieved, but does not generate a vector-index outbox item.
    """
    news_repository.add_snapshot(_snapshot())
    failed = _event("evt_failed").model_copy(
        update={
            "processing_status": DocumentStatus.PARSE_FAILED,
            "processing_error": "parse failed",
            "content": None,
        }
    )

    news_repository.add_document_event(failed, publishable=True)

    assert news_repository.get_document_event("evt_failed") == failed
    assert news_repository.claim_outbox(topic="vector_index", limit=10) == []


def test_dedup_and_repost_chain_are_persistent(news_repository):
    """Dedup records and repost edges are queryable after persistence.

    Verifies that a duplicate event can be linked to a canonical event with a
    dedup record, and that the repost chain can be reconstructed from stored
    edges.
    """
    news_repository.add_snapshot(_snapshot())
    canonical = _event("evt_canonical", "https://exchange.example/a")
    duplicate = _event("evt_dup", "https://media.example/a")
    news_repository.add_document_event(canonical, publishable=False)
    news_repository.add_document_event(duplicate, publishable=False)

    news_repository.add_dedup_record(
        duplicate_event_id=duplicate.event_id,
        canonical_event_id=canonical.event_id,
        reason="vector_similarity",
        similarity_score=0.97,
    )
    news_repository.add_repost_edge(
        parent_event_id=canonical.event_id,
        child_event_id=duplicate.event_id,
        reason="vector_similarity",
    )

    record = news_repository.get_dedup_record(duplicate.event_id)
    assert record is not None
    assert record.canonical_event_id == canonical.event_id
    assert record.reason == "vector_similarity"

    chain = news_repository.list_repost_chain(canonical.event_id)
    assert [(edge.parent_event_id, edge.child_event_id) for edge in chain] == [
        (canonical.event_id, duplicate.event_id)
    ]
