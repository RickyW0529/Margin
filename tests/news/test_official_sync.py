"""Official filing cursor sync safety tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from margin.news.db_models import (
    DocumentEventRow,
    DocumentOutboxRow,
    RawSnapshotRow,
    SourceCursorRow,
)
from margin.news.discovery import DiscoveredDocument
from margin.news.models import SourceLevel, make_document_event
from margin.news.official_sync import OfficialFilingSyncService
from margin.news.repository import NewsRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def news_repository(database_url: str) -> Iterator[NewsRepository]:
    """Create a clean repository for official sync tests."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (DocumentOutboxRow, DocumentEventRow, RawSnapshotRow, SourceCursorRow):
            session.query(row).delete()
    yield NewsRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def filing_record(cursor: str) -> DiscoveredDocument:
    """Build a discovered filing fixture."""
    return DiscoveredDocument(
        external_id="filing-1",
        title="平安银行公告",
        source_url="https://example.com/a.pdf",
        published_at=datetime(2026, 6, 22, tzinfo=UTC),
        cursor=cursor,
    )


class FakeOfficialDiscovery:
    """Discovery fake returning preconfigured records."""

    def __init__(self, records: list[DiscoveredDocument]) -> None:
        """Initialize the instance."""
        self.records = records
        self.seen_cursor: str | None = None

    def discover(self, cursor: str | None, limit: int) -> list[DiscoveredDocument]:
        """discover."""
        self.seen_cursor = cursor
        return self.records[:limit]


class FakeAcquirer:
    """Acquirer fake that returns a durable document event."""

    def acquire(self, source_name: str, url: str, **kwargs):
        """acquire."""
        return make_document_event(
            source_url=url,
            source_name=source_name,
            source_level=SourceLevel.L1,
            title=str(kwargs.get("title_override") or "公告"),
            content="公告正文 000001.SZ",
            symbols=["000001.SZ"],
            published_at=kwargs.get("published_at"),
        )


class FailingAcquirer:
    """Acquirer fake that simulates a download/persist failure before event creation."""

    def acquire(self, source_name: str, url: str, **kwargs):
        """acquire."""
        raise RuntimeError("download failed")


def test_official_cursor_advances_only_after_event_persisted(
    news_repository: NewsRepository,
) -> None:
    """official cursor advances only after event persisted."""
    discovery = FakeOfficialDiscovery(records=[filing_record(cursor="page-2")])
    service = OfficialFilingSyncService(news_repository, discovery, FakeAcquirer())

    run = service.sync(source_name="sse", cursor_key="announcements", limit=10)

    assert run.persisted_events == 1
    assert news_repository.get_cursor("sse", "announcements") == "page-2"


def test_official_cursor_stays_put_when_persist_fails(
    news_repository: NewsRepository,
) -> None:
    """official cursor stays put when persist fails."""
    discovery = FakeOfficialDiscovery(records=[filing_record(cursor="page-2")])
    service = OfficialFilingSyncService(news_repository, discovery, FailingAcquirer())

    run = service.sync(source_name="sse", cursor_key="announcements", limit=10)

    assert run.failed_records == 1
    assert news_repository.get_cursor("sse", "announcements") is None
